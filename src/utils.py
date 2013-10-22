

def ignore_exception(IgnoreException=Exception,DefaultVal=None):
    """ Decorator for ignoring exception from a function
    e.g.   @ignore_exception(DivideByZero)
    e.g.2. ignore_exception(DivideByZero)(Divide)(2/0)
    """
    def dec(function):
        def _dec(*args, **kwargs):
            try:
                return function(*args, **kwargs)
            except IgnoreException:
                return DefaultVal if not hasattr(DefaultVal, "__call__") else DefaultVal()
        return _dec
    return dec

def filter_dict(d, filter_list): 
    if type(filter_list) == str:
        filter_list = filter_list.split()
    return dict( (k,v) for k,v in d.iteritems() if k not in filter_list )
