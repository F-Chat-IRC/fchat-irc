import logging
import traceback as tb

def traceback(func):
    def call_function(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception, e:
            logging.error(tb.format_exc())
    return call_function

