from contextlib import contextmanager

@contextmanager
def resource(log):
    log.append("acquire")
    try:
        yield
    finally:
        log.append("release")