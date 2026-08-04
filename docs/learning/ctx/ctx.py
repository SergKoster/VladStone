class Resource:
    def __init__(self, log: list[str]):
        self.log = log

    def __enter__(self):
        self.log.append("acquire")
        return self
    
    def __exit__(self, exc_type, exc, tb):
        self.log.append("release")
