class StopBatch(Exception):
    pass



def process(items, fn):
    result = []

    for item in items:
        try:
            if item == 52:
                raise StopBatch
            else:
                miditem = fn(item)
        except StopBatch:
            raise
        except Exception:
            continue
        result.append(miditem)

    return result