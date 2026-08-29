from huggingface_hub import HfApi

from Authentication.config import settings


class BucketError(Exception):
    pass


def upload(content: bytes, remote_path: str) -> None:
    if not settings.huggingface_token:
        raise BucketError("Hugging Face storage is not configured")
    try:
        HfApi(token=settings.huggingface_token).batch_bucket_files(
            settings.huggingface_bucket, add=[(content, remote_path)]
        )
    except Exception as error:
        raise BucketError("Could not upload the original document to Hugging Face") from error


def delete(remote_path: str) -> None:
    if not settings.huggingface_token:
        raise BucketError("Hugging Face storage is not configured")
    try:
        HfApi(token=settings.huggingface_token).batch_bucket_files(
            settings.huggingface_bucket, delete=[remote_path]
        )
    except Exception as error:
        raise BucketError("Could not delete the original document from Hugging Face") from error
