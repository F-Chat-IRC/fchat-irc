'''This module is a convenient standalone that provides an easy decorator function @traceback.
This allows you to log all errors properly without having to fetch stdin,
and gives more detail than the regular traceback.'''
import logging
import traceback as tb

def traceback(func):
    def call_function(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception, e:
            logging.error(tb.format_exc())
    return call_function

