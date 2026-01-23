import os
import boto3
from botocore.exceptions import ClientError
import logging

# Configure silent logging for boto3 and botocore
logging.getLogger('boto3').setLevel(logging.CRITICAL)
logging.getLogger('botocore').setLevel(logging.CRITICAL)
logging.getLogger('s3transfer').setLevel(logging.CRITICAL)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

def upload_file_to_s3(file_path, bucket_name, s3_key):
    """
    Upload a file to an S3 bucket silently.
    """
    access_key = os.environ.get('AWS_ACCESS_KEY_ID')
    secret_key = os.environ.get('AWS_SECRET_ACCESS_KEY')
    region = os.environ.get('AWS_REGION', 'us-east-1')

    if not access_key or not secret_key:
        return False

    s3_client = boto3.client(
        's3',
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region
    )
    try:
        # Extra arguments for public read if needed, but the user didn't specify.
        # Given the bucket name, it might be for a web app.
        s3_client.upload_file(file_path, bucket_name, s3_key)
        return True
    except ClientError:
        return False
    except Exception:
        return False


from botocore.config import Config
import json
import time as time_module

# Simple in-memory cache for gallery clips
_clips_cache = {
    "data": None,
    "timestamp": 0
}
CACHE_TTL_SECONDS = 300  # 5 minutes

def get_s3_client():
    """Returns an authenticated S3 client."""
    access_key = os.environ.get('AWS_ACCESS_KEY_ID')
    secret_key = os.environ.get('AWS_SECRET_ACCESS_KEY')
    region = os.environ.get('AWS_REGION', 'us-east-1')

    if not access_key or not secret_key:
        return None

    return boto3.client(
        's3',
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
        config=Config(signature_version='s3v4')
    )

def generate_presigned_url(bucket_name, object_key, expiration=3600):
    """Generate a presigned URL to share an S3 object."""
    s3_client = get_s3_client()
    if not s3_client:
        return None
    try:
        response = s3_client.generate_presigned_url('get_object',
                                                    Params={'Bucket': bucket_name,
                                                            'Key': object_key},
                                                    ExpiresIn=expiration)
        return response
    except ClientError as e:
        logger.error(e)
        return None

def list_all_clips(bucket_name=None, limit=50, force_refresh=False):
    """
    List recent clips from the S3 bucket by finding metadata files.
    Returns a list of dicts containing clip info and signed URLs.
    
    Args:
        bucket_name: S3 bucket name (defaults to AWS_S3_BUCKET env var)
        limit: Maximum number of clips to return (default 50 for speed)
        force_refresh: If True, bypass cache
    """
    global _clips_cache
    
    # Check cache first
    now = time_module.time()
    if not force_refresh and _clips_cache["data"] is not None:
        if now - _clips_cache["timestamp"] < CACHE_TTL_SECONDS:
            cached = _clips_cache["data"]
            return cached[:limit] if limit else cached
    
    if not bucket_name:
        bucket_name = os.environ.get('AWS_S3_BUCKET', 'openshorts.app-clips')

    s3_client = get_s3_client()
    if not s3_client:
        return []

    all_clips = []
    
    try:
        # List all objects in bucket
        # Note: For very large buckets, pagination is needed. 
        # Assuming reasonable size for now, but adding continuation token support is best practice.
        paginator = s3_client.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket=bucket_name)

        metadata_files = []
        for page in pages:
            if 'Contents' in page:
                for obj in page['Contents']:
                    if obj['Key'].endswith('_metadata.json'):
                         metadata_files.append(obj)
        
        # Sort metadata by LastModified (newest first)
        metadata_files.sort(key=lambda x: x['LastModified'], reverse=True)

        for meta_obj in metadata_files:
            key = meta_obj['Key']
            # key format: {job_id}/..._metadata.json
            
            # Read metadata content
            try:
                obj_resp = s3_client.get_object(Bucket=bucket_name, Key=key)
                content = obj_resp['Body'].read().decode('utf-8')
                data = json.loads(content)
                
                parts = key.split('/')
                job_id = parts[0] if len(parts) > 1 else "unknown"
                # Filename base for clips in same folder
                # Meta key: "job_id/filename_metadata.json"
                # Base name in metadata usually matches filename without ext
                meta_filename = os.path.basename(key) 
                base_name = meta_filename.replace('_metadata.json', '')
                
                clips_data = data.get('shorts', [])
                
                for i, clip in enumerate(clips_data):
                    clip_filename = f"{base_name}_clip_{i+1}.mp4"
                    clip_key = f"{job_id}/{clip_filename}"
                    
                    # Generate signed URL
                    signed_url = generate_presigned_url(bucket_name, clip_key, expiration=7200) # 2 hours
                    
                    if signed_url:
                        all_clips.append({
                            "job_id": job_id,
                            "index": i,
                            "url": signed_url,
                            "title": clip.get('video_title_for_youtube_short', 'Untitled Clip'),
                            "tiktok_desc": clip.get('video_description_for_tiktok', ''),
                            "insta_desc": clip.get('video_description_for_instagram', ''),
                            "created_at": meta_obj['LastModified'].isoformat(),
                            "duration": clip.get('end', 0) - clip.get('start', 0)
                        })
                        
                        # Early exit if we have enough clips
                        if limit and len(all_clips) >= limit:
                            break
                
                # Early exit if we have enough clips
                if limit and len(all_clips) >= limit:
                    break

            except Exception as e:
                logger.error(f"Error processing metadata {key}: {e}")
                continue

    except Exception as e:
        logger.error(f"Error listing bucket: {e}")
        return []
    
    # Update cache with full results (keep for pagination later)
    _clips_cache["data"] = all_clips
    _clips_cache["timestamp"] = now

    return all_clips[:limit] if limit else all_clips

def upload_job_artifacts(directory, job_id):
    """
    Upload all generated clips and metadata for a job to S3.
    """
    bucket_name = os.environ.get('AWS_S3_BUCKET', 'openshorts.app-clips')
    
    if not os.path.exists(directory):
        return

    for filename in os.listdir(directory):
        # Upload .mp4 clips and the metadata JSON
        if (filename.endswith(".mp4") or filename.endswith(".json")) and not filename.startswith("temp_"):
            file_path = os.path.join(directory, filename)
            s3_key = f"{job_id}/{filename}"
            upload_file_to_s3(file_path, bucket_name, s3_key)


