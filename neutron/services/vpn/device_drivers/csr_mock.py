"""Mock requests to Cisco Cloud Services Router."""

from functools import wraps
from httmock import urlmatch, all_requests
import requests
from webob import exc as wexc

# TODO REMOVE....
def repeat(n):
    """Decorator to limit the number of times a handler is called.
    
    HTTMock mocks calls to the requests libary, by using one or more
    "handlers" that are registered. The first handler is tried, and
    if it returns None (instead of a dict), the next handler is tried,
    until a dict is returned, or no more handlers exist. To allow
    different responses for a single resource, we can use this decorator
    to limit the number of times a handler will respond (returning None,
    when the limit is reached), thereby allowing other handlers to try
    to respond."""
    
    class static:
        times = n
    def decorator(func):
        @wraps(func)
        def wrapped(*args, **kwargs):
            if static.times == 0:
                return None
            static.times -= 1
            return func(*args, **kwargs)
        return wrapped
    return decorator

def once_for(resource):
    """Decorator to invoke handler once for a specific resource.
    
    This will call the handler the first time it is invoked for a
    specific resource. Subsequent calls will return None, telling
    the mock mechanism that there is no handler for this resource,
    allowing additional handlers (if any) to be attempted."""
    
    class static:
        times = 1
        target_resource = resource
    def decorator(func):
        @wraps(func)
        def wrapped(*args, **kwargs):
            if static.times == 0:
                return None
            if static.target_resource in args[0].path:
                static.times -= 1
                return func(*args, **kwargs)
            else:
                return None # Not for this resource
        return wrapped
    return decorator


@urlmatch(netloc=r'localhost')
def token(url, request):
    if 'auth/token-services' in url.path:
        return {'status_code': wexc.HTTPCreated.code,
                'content': {'token-id': 'dummy-token'}}

@urlmatch(netloc=r'localhost')
def token_unauthorized(url, request):
    if 'auth/token-services' in url.path:
        return {'status_code': wexc.HTTPUnauthorized.code}

@urlmatch(netloc=r'wrong-host')
def token_wrong_host(url, request):
    raise requests.ConnectionError()
    
@all_requests
def token_timeout(url, request):
    raise requests.Timeout()

@all_requests
def timeout(url, request):
    """Simulated timeout of a normal request.
    
    This handler is conditional, and will only apply to unit test
    cases that match the resource."""
    
    if ('global/host-name' in url.path or 
        'interfaces/GigabitEthernet' in url.path):
        if not request.headers.get('X-auth-token', None):
            return {'status_code': wexc.HTTPUnauthorized.code}
        raise requests.Timeout()

@urlmatch(netloc=r'localhost')
def no_such_resource(url, request):
    if 'no/such/request' in url.path:
        return {'status_code': wexc.HTTPNotFound.code}

@urlmatch(netloc=r'localhost')
def get(url, request):
    if 'global/host-name' in url.path:
        if not request.headers.get('X-auth-token', None):
            return {'status_code': wexc.HTTPUnauthorized.code}
        return {'status_code': wexc.HTTPOk.code,
                'content': {u'kind': u'object#host-name',
                            u'host-name': u'Router'}}
    if 'global/local-users' in url.path:
        if not request.headers.get('X-auth-token', None):
            return {'status_code': wexc.HTTPUnauthorized.code}
        return {'status_code': wexc.HTTPOk.code,
                'content': {u'kind': u'collection#local-user', 
                            u'users': ['peter', 'paul', 'mary']}}

@once_for('global/host-name')
@urlmatch(netloc=r'localhost')
def expired_get(url, request):
    """Simulate access denied failure when get from this resource.
    
    This handler will be ignored (by returning None), on any subsequent
    accesses to this resource."""
    
    return {'status_code': wexc.HTTPUnauthorized.code}

@once_for('interfaces/GigabitEthernet1')
@urlmatch(netloc=r'localhost')
def expired_post_put(url, request):
    """Simulate access denied failure when post/put to this resource.
    
    This handler will be ignored (by returning None), on any subsequent
    accesses to this resource."""
    
    return {'status_code': wexc.HTTPUnauthorized.code}

def post(url, request):
    if 'interfaces/GigabitEthernet' in url.path:
        if not request.headers.get('X-auth-token', None):
            return {'status_code': wexc.HTTPUnauthorized.code}
        return {'status_code': wexc.HTTPNoContent.code}
    if 'global/local-users' in url.path:
        if not request.headers.get('X-auth-token', None):
            return {'status_code': wexc.HTTPUnauthorized.code}
        return {'status_code': wexc.HTTPCreated.code}

def put(url, request):
    if 'interfaces/GigabitEthernet' in url.path:
        if not request.headers.get('X-auth-token', None):
            return {'status_code': wexc.HTTPUnauthorized.code}
        return {'status_code': wexc.HTTPNoContent.code}

def delete(url, request):
    if 'global/local-users' in url.path:
        if not request.headers.get('X-auth-token', None):
            return {'status_code': wexc.HTTPUnauthorized.code}
        return {'status_code': wexc.HTTPNoContent.code}
