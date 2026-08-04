from contextlib import contextmanager

@contextmanager
def Recource(log: list[str]):
    log.append("acquire")
    
    try:
        yield
    finally:
        log.append("release")


