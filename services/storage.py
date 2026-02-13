from datetime import timedelta

def upload_file(bucket, path: str, file, content_type: str):
    blob = bucket.blob(path)
    blob.upload_from_file(file, content_type=content_type)
    return True

def signed_url(bucket, path: str, minutes: int = 15) -> str:
    return bucket.blob(path).generate_signed_url(expiration=timedelta(minutes=minutes))

def delete_if_exists(bucket, path: str):
    try:
        bucket.blob(path).delete()
    except Exception:
        pass
