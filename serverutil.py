"""Utility functions for the server.

This includes the interface from the server implementation to the
payment channel and lightning network APIs.

requires_auth -- decorator which makes a view function require authentication
authenticate_before_request -- a before_request callback for auth
api_factory -- returns a flask Blueprint or equivalent, along with a decorator
               making functions availiable as RPCs, and a base class for
               SQLAlchemy Declarative database models.

Signals:
WALLET_NOTIFY: sent when bitcoind tells us it has a transaction.
- tx = txid
BLOCK_NOTIFY: send when bitcoind tells us it has a block
- block = block hash
"""

import os.path
from functools import wraps
from flask import Flask, current_app, Response, request, Blueprint
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.types import TypeDecorator
from blinker import Namespace
from sqlalchemy import LargeBinary, Text
from jsonrpc.backend.flask import JSONRPCAPI
import bitcoin.core.serialize
from jsonrpcproxy import SmartDispatcher

app = Flask(__name__)
database = SQLAlchemy(app)

SIGNALS = Namespace()
WALLET_NOTIFY = SIGNALS.signal('WALLET_NOTIFY')
BLOCK_NOTIFY = SIGNALS.signal('BLOCK_NOTIFY')

# Copied from http://flask.pocoo.org/snippets/8/
def check_auth(username, password):
    """This function is called to check if a username /
    password combination is valid.
    """
    return (username == current_app.config['rpcuser'] and
            password == current_app.config['rpcpassword'])

def authenticate():
    """Sends a 401 response that enables basic auth"""
    return Response(
        'Could not verify your access level for that URL.\n'
        'You have to login with proper credentials', 401,
        {'WWW-Authenticate': 'Basic realm="Login Required"'})

def requires_auth(view):
    """Require basic authentication on requests to this view.

    Also only accept requests from localhost.
    """
    @wraps(view)
    def decorated(*args, **kwargs):
        """Decorated version of view that checks authentication."""
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        if request.remote_addr != "127.0.0.1":
            return Response("Access outside 127.0.0.1 forbidden", 403)
        return view(*args, **kwargs)
    return decorated

def authenticate_before_request():
    """before_request callback to perform authentication."""
    return requires_auth(lambda: None)()

def api_factory(name):
    """Construct a Blueprint and a REMOTE decorator to set up an API.

    RPC calls are availiable at the url /name/
    """
    api = Blueprint(name, __name__, url_prefix='/'+name)

    # set up the database
    def setup_bind(state):
        """Add the database to the config."""
        database_path = os.path.join(state.app.config['datadir'], name + '.dat')
        state.app.config['SQLALCHEMY_BINDS'][name] = 'sqlite:///' + database_path
    api.record_once(setup_bind)
    def initialize_database():
        """Create the database."""
        database.create_all(name)
    api.before_app_first_request(initialize_database)

    # create a base class for models
    class BoundMeta(type(database.Model)):
        """Metaclass for Model which allows __abstract__ base classes."""
        def __init__(self, cls_name, bases, attrs):
            assert '__bind_key__' not in attrs
            if not attrs.get('__abstract__', False):
                attrs['__bind_key__'] = name
            super(BoundMeta, self).__init__(cls_name, bases, attrs)
    class BoundModel(database.Model, metaclass=BoundMeta):
        """Base class for models which have __bind_key__ set automatically."""
        __abstract__ = True
        query = object.__getattribute__(database.Model, 'query')
        def __init__(self, *args, **kwargs):
            super(BoundModel, self).__init__(*args, **kwargs)

    # create a JSON-RPC API endpoint
    rpc_api = JSONRPCAPI(SmartDispatcher())
    assert type(rpc_api.dispatcher == SmartDispatcher)
    api.add_url_rule('/', 'rpc', rpc_api.as_view(), methods=['POST'])

    return api, rpc_api.dispatcher.add_method, BoundModel

class ImmutableSerializableType(TypeDecorator):
    """Converts bitcoin-lib ImmutableSerializable instances for the DB."""

    impl = LargeBinary

    def __init__(self, subtype=bitcoin.core.serialize.ImmutableSerializable):
        self.subtype = subtype
        super(ImmutableSerializableType, self).__init__()

    @property
    def python_type(self):
        return self.subtype

    def process_bind_param(self, value, dialect):
        if value is not None:
            value = value.serialize()
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            value = self.subtype.deserialize(value)
        return value

    def process_literal_param(self, value, dialect):
        raise NotImplementedError()


class Base58DataType(TypeDecorator):
    """Converts bitcoin-lib Base58Data instances for the DB."""

    impl = Text

    def __init__(self, subtype=bitcoin.base58.CBase58Data):
        self.subtype = subtype
        super(Base58DataType, self).__init__()

    @property
    def python_type(self):
        return self.subtype

    def process_bind_param(self, value, dummy_dialect):
        if value is not None:
            value = str(value)
        return value

    def process_result_value(self, value, dummy_dialect):
        if value is not None:
            value = self.subtype(value)
        return value

    def process_literal_param(self, value, dialect):
        raise NotImplementedError()
