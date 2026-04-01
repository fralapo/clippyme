import os
import uuid
import subprocess
import threading
import json
import shutil
import glob
import time
import asyncio
from dotenv import load_dotenv
from typing import Dict, Optional, List
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, Header, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

load_dotenv()

# Constants
UPLOAD_DIR = "uploads"
OUTPUT_DIR = "output"
DATA_DIR = "data"
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

def load_persistent_config():
    """Load config from JSON file if exists, falling back to environment variables."""
    config = {
        "GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY", ""),
        "ELEVENLABS_API_KEY": os.environ.get("X_ELEVENLABS_KEY", ""),
        "UPLOAD_POST_API_KEY": os.environ.get("X_UPLOAD_POST_KEY", ""),
        "AWS_ACCESS_KEY_ID": os.environ.get("AWS_ACCESS_KEY_ID", ""),
        "AWS_SECRET_ACCESS_KEY": os.environ.get("AWS_SECRET_ACCESS_KEY", ""),
        "AWS_S3_BUCKET": os.environ.get("AWS_S3_BUCKET", ""),
        "AWS_S3_PUBLIC_BUCKET": os.environ.get("AWS_S3_PUBLIC_BUCKET", ""),
        "YOUTUBE_COOKIES": os.environ.get("YOUTUBE_COOKIES", "")
    }
    
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                persistent = json.load(f)
                config.update(persistent)
        except Exception as e:
            print(f"⚠️ Error loading config.json: {e}")
            
    return config

def save_persistent_config(new_config: dict):
    """Save new configuration to JSON file."""
    try:
        # Load existing first to merge
        current = {}
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r") as f:
                current = json.load(f)
        
        current.update(new_config)
        with open(CONFIG_FILE, "w") as f:
            json.dump(current, f, indent=4)
            
        # Update current process environment so sub-processes (main.py) see them
        for key, value in new_config.items():
            if value:
                os.environ[key] = str(value)
        return True
    except Exception as e:
        print(f"❌ Error saving config.json: {e}")
        return False

# Initial load to env
save_persistent_config(load_persistent_config())

# Configuration
# Default to 1 if not set, but user can set higher for powerful servers
MAX_CONCURRENT_JOBS = int(os.environ.get("MAX_CONCURRENT_JOBS", "5"))
MAX_FILE_SIZE_MB = 2048  # 2GB limit
JOB_RETENTION_SECONDS = 3600  # 1 hour retention

# Application State
job_queue = asyncio.Queue()
jobs: Dict[str, Dict] = {}
# Semester to limit concurrency to MAX_CONCURRENT_JOBS
concurrency_semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)

def _relocate_root_job_artifacts(job_id: str, job_output_dir: str) -> bool:
    """
    Backward-compat rescue:
    If main.py accidentally wrote metadata/clips into OUTPUT_DIR root (e.g. output/<jobid>_...),
    move them into output/<job_id>/ so the API can find and serve them.
    """
    try:
        os.makedirs(job_output_dir, exist_ok=True)
        root = OUTPUT_DIR
        pattern = os.path.join(root, f"{job_id}_*_metadata.json")
        meta_candidates = sorted(glob.glob(pattern), key=lambda p: os.path.getmtime(p), reverse=True)
        if not meta_candidates:
            return False

        # Move the newest metadata and its associated clips.
        metadata_path = meta_candidates[0]
        base_name = os.path.basename(metadata_path).replace("_metadata.json", "")

        # Move metadata
        dest_metadata = os.path.join(job_output_dir, os.path.basename(metadata_path))
        if os.path.abspath(metadata_path) != os.path.abspath(dest_metadata):
            shutil.move(metadata_path, dest_metadata)

        # Move any clips that match the same base_name into the job folder
        clip_pattern = os.path.join(root, f"{base_name}_clip_*.mp4")
        for clip_path in glob.glob(clip_pattern):
            dest_clip = os.path.join(job_output_dir, os.path.basename(clip_path))
            if os.path.abspath(clip_path) != os.path.abspath(dest_clip):
                shutil.move(clip_path, dest_clip)

        # Also move any temp_ clips that might remain
        temp_clip_pattern = os.path.join(root, f"temp_{base_name}_clip_*.mp4")
        for clip_path in glob.glob(temp_clip_pattern):
            dest_clip = os.path.join(job_output_dir, os.path.basename(clip_path))
            if os.path.abspath(clip_path) != os.path.abspath(dest_clip):
                shutil.move(clip_path, dest_clip)

        return True
    except Exception:
        return False

async def cleanup_jobs():
    """Background task to remove old jobs and files."""
    import time
    print("🧹 Cleanup task started.")
    while True:
        try:
            await asyncio.sleep(300) # Check every 5 minutes
            now = time.time()
            
            # Simple directory cleanup based on modification time
            # Check OUTPUT_DIR
            for job_id in os.listdir(OUTPUT_DIR):
                job_path = os.path.join(OUTPUT_DIR, job_id)
                if os.path.isdir(job_path):
                    if now - os.path.getmtime(job_path) > JOB_RETENTION_SECONDS:
                        print(f"🧹 Purging old job: {job_id}")
                        shutil.rmtree(job_path, ignore_errors=True)
                        if job_id in jobs:
                            del jobs[job_id]

            # Cleanup Uploads
            for filename in os.listdir(UPLOAD_DIR):
                file_path = os.path.join(UPLOAD_DIR, filename)
                try:
                    if now - os.path.getmtime(file_path) > JOB_RETENTION_SECONDS:
                         os.remove(file_path)
                except Exception: pass

        except Exception as e:
            print(f"⚠️ Cleanup error: {e}")

async def process_queue():
    """Background worker to process jobs from the queue with concurrency limit."""
    print(f"🚀 Job Queue Worker started with {MAX_CONCURRENT_JOBS} concurrent slots.")
    while True:
        try:
            # Wait for a job
            job_id = await job_queue.get()
            
            # Acquire semaphore slot (waits if max jobs are running)
            await concurrency_semaphore.acquire()
            print(f"🔄 Acquired slot for job: {job_id}")

            # Process in background task to not block the loop (allowing other slots to fill)
            asyncio.create_task(run_job_wrapper(job_id))
            
        except Exception as e:
            print(f"❌ Queue dispatch error: {e}")
            await asyncio.sleep(1)

async def run_job_wrapper(job_id):
    """Wrapper to run job and release semaphore"""
    try:
        job = jobs.get(job_id)
        if job:
            await run_job(job_id, job)
    except Exception as e:
         print(f"❌ Job wrapper error {job_id}: {e}")
    finally:
        # Always release semaphore and mark queue task done
        concurrency_semaphore.release()
        job_queue.task_done()
        print(f"✅ Released slot for job: {job_id}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start worker and cleanup
    worker_task = asyncio.create_task(process_queue())
    cleanup_task = asyncio.create_task(cleanup_jobs())
    yield
    # Cleanup (optional: cancel worker)

app = FastAPI(lifespan=lifespan)

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files for serving videos
app.mount("/videos", StaticFiles(directory=OUTPUT_DIR), name="videos")

# Mount static files for serving thumbnails
THUMBNAILS_DIR = os.path.join(OUTPUT_DIR, "thumbnails")
os.makedirs(THUMBNAILS_DIR, exist_ok=True)
app.mount("/thumbnails", StaticFiles(directory=THUMBNAILS_DIR), name="thumbnails")

@app.get("/")
async def root():
    return {"status": "online", "message": "ClippyMe API is running"}

@app.get("/api/health")
async def health():
    return {"status": "healthy"}

class ProcessRequest(BaseModel):
    url: str

def enqueue_output(out, job_id):
    """Reads output from a subprocess and appends it to jobs logs."""
    try:
        for line in iter(out.readline, b''):
            decoded_line = line.decode('utf-8').strip()
            if decoded_line:
                print(f"📝 [Job Output] {decoded_line}")
                if job_id in jobs:
                    jobs[job_id]['logs'].append(decoded_line)
    except Exception as e:
        print(f"Error reading output for job {job_id}: {e}")
    finally:
        out.close()

async def run_job(job_id, job_data):
    """Executes the subprocess for a specific job."""
    
    cmd = job_data['cmd']
    env = job_data['env']
    output_dir = job_data['output_dir']
    
    jobs[job_id]['status'] = 'processing'
    jobs[job_id]['logs'].append("Job started by worker.")
    print(f"🎬 [run_job] Executing command for {job_id}: {' '.join(cmd)}")
    
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, # Merge stderr to stdout
            env=env,
            cwd=os.getcwd()
        )
        
        # We need to capture logs in a thread because Popen isn't async
        t_log = threading.Thread(target=enqueue_output, args=(process.stdout, job_id))
        t_log.daemon = True
        t_log.start()
        
        # Async wait for process with incremental updates
        start_wait = time.time()
        while process.poll() is None:
            await asyncio.sleep(2)
            
            # Check for partial results every 2 seconds
            # Look for metadata file
            try:
                json_files = glob.glob(os.path.join(output_dir, "*_metadata.json"))
                if json_files:
                    target_json = json_files[0]
                    # Read metadata (it might be being written to, so simple try/except or just read)
                    # Use a lock or just robust read? json.load might fail if file is partial.
                    # Usually main.py writes it once at start (based on my review).
                    if os.path.getsize(target_json) > 0:
                        with open(target_json, 'r') as f:
                            data = json.load(f)
                            
                        base_name = os.path.basename(target_json).replace('_metadata.json', '')
                        clips = data.get('shorts', [])
                        cost_analysis = data.get('cost_analysis')
                        
                        # Check which clips actually exist on disk
                        ready_clips = []
                        for i, clip in enumerate(clips):
                             clip_filename = f"{base_name}_clip_{i+1}.mp4"
                             clip_path = os.path.join(output_dir, clip_filename)
                             if os.path.exists(clip_path) and os.path.getsize(clip_path) > 0:
                                 # Checking if file is growing? For now assume if it exists and main.py moves it there, it's done.
                                 # main.py writes to temp_... then moves to final name. So presence means ready!
                                 clip['video_url'] = f"/videos/{job_id}/{clip_filename}"
                                 ready_clips.append(clip)
                        
                        if ready_clips:
                             jobs[job_id]['result'] = {'clips': ready_clips, 'cost_analysis': cost_analysis}
            except Exception as e:
                # Ignore read errors during processing
                pass

        returncode = process.returncode
        
        if returncode == 0:
            jobs[job_id]['status'] = 'completed'
            jobs[job_id]['logs'].append("Process finished successfully.")
            
            # Find result JSON
            json_files = glob.glob(os.path.join(output_dir, "*_metadata.json"))
            if not json_files:
                # Backward-compat rescue if outputs were written to OUTPUT_DIR root
                if _relocate_root_job_artifacts(job_id, output_dir):
                    json_files = glob.glob(os.path.join(output_dir, "*_metadata.json"))
            if json_files:
                target_json = json_files[0] 
                with open(target_json, 'r') as f:
                    data = json.load(f)
                
                # Enhance result with video URLs
                base_name = os.path.basename(target_json).replace('_metadata.json', '')
                clips = data.get('shorts', [])
                cost_analysis = data.get('cost_analysis')

                for i, clip in enumerate(clips):
                     clip_filename = f"{base_name}_clip_{i+1}.mp4"
                     clip['video_url'] = f"/videos/{job_id}/{clip_filename}"
                
                jobs[job_id]['result'] = {'clips': clips, 'cost_analysis': cost_analysis}
            else:
                 jobs[job_id]['status'] = 'failed'
                 jobs[job_id]['logs'].append("No metadata file generated.")
        else:
            jobs[job_id]['status'] = 'failed'
            jobs[job_id]['logs'].append(f"Process failed with exit code {returncode}")
            
    except Exception as e:
        jobs[job_id]['status'] = 'failed'
        jobs[job_id]['logs'].append(f"Execution error: {str(e)}")

@app.post("/api/process")
async def process_endpoint(
    request: Request,
    file: Optional[UploadFile] = File(None),
    url: Optional[str] = Form(None),
    cookies_file: Optional[UploadFile] = File(None)
):
    api_key = request.headers.get("X-Gemini-Key")
    if not api_key:
        raise HTTPException(status_code=400, detail="Missing X-Gemini-Key header")
    
    # Handle JSON body manually for URL payload
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        body = await request.json()
        url = body.get("url")
    
    if not url and not file:
        raise HTTPException(status_code=400, detail="Must provide URL or File")

    job_id = str(uuid.uuid4())
    job_output_dir = os.path.join(OUTPUT_DIR, job_id)
    os.makedirs(job_output_dir, exist_ok=True)
    
    # Prepare Command
    cmd = ["python", "-u", "main.py"] # -u for unbuffered
    env = os.environ.copy()
    env["GEMINI_API_KEY"] = api_key # Override with key from request
    
    if url:
        cmd.extend(["-u", url])
        if cookies_file:
            cookies_path = os.path.join(UPLOAD_DIR, f"cookies_{job_id}.txt")
            content_bytes = await cookies_file.read()
            with open(cookies_path, "wb") as buffer:
                buffer.write(content_bytes)
            cmd.extend(["-c", cookies_path])
    else:
        # Save uploaded file with size limit check
        input_path = os.path.join(UPLOAD_DIR, f"{job_id}_{file.filename}")
        
        # Read file in chunks to check size
        size = 0
        limit_bytes = MAX_FILE_SIZE_MB * 1024 * 1024
        
        with open(input_path, "wb") as buffer:
            while content := await file.read(1024 * 1024): # Read 1MB chunks
                size += len(content)
                if size > limit_bytes:
                    os.remove(input_path)
                    shutil.rmtree(job_output_dir)
                    raise HTTPException(status_code=413, detail=f"File too large. Max size {MAX_FILE_SIZE_MB}MB")
                buffer.write(content)
                
        cmd.extend(["-i", input_path])

    cmd.extend(["-o", job_output_dir])

    # Enqueue Job
    jobs[job_id] = {
        'status': 'queued',
        'logs': [f"Job {job_id} queued."],
        'cmd': cmd,
        'env': env,
        'output_dir': job_output_dir
    }
    
    await job_queue.put(job_id)
    
    return {"job_id": job_id, "status": "queued"}

@app.get("/api/status/{job_id}")
async def get_status(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job = jobs[job_id]
    return {
        "status": job['status'],
        "logs": job['logs'],
        "result": job.get('result')
    }

@app.get("/api/config")
async def get_config():
    """Return current active configuration (keys are partially masked for safety)."""
    config = load_persistent_config()
    masked = {}
    for k, v in config.items():
        if v and len(v) > 8:
            masked[k] = f"{v[:4]}...{v[-4:]}"
        else:
            masked[k] = v
    return masked

class ConfigUpdateRequest(BaseModel):
    keys: dict

@app.post("/api/config")
async def update_config(req: ConfigUpdateRequest):
    """Update and persist API keys."""
    if save_persistent_config(req.keys):
        return {"success": True, "message": "Configuration updated and persisted."}
    else:
        raise HTTPException(status_code=500, detail="Failed to save configuration.")

from editor import VideoEditor
from subtitles import generate_srt, burn_subtitles, generate_srt_from_video

class EditRequest(BaseModel):
    job_id: str
    clip_index: int
    api_key: Optional[str] = None
    input_filename: Optional[str] = None

@app.post("/api/edit")
async def edit_clip(
    req: EditRequest,
    x_gemini_key: Optional[str] = Header(None, alias="X-Gemini-Key")
):
    # Determine API Key
    final_api_key = req.api_key or x_gemini_key or os.environ.get("GEMINI_API_KEY")
    
    if not final_api_key:
        raise HTTPException(status_code=400, detail="Missing Gemini API Key (Header or Body)")

    if req.job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job = jobs[req.job_id]
    if 'result' not in job or 'clips' not in job['result']:
        raise HTTPException(status_code=400, detail="Job result not available")
        
    try:
        # Resolve Input Path: Prefer explict input_filename from frontend (chaining edits)
        if req.input_filename:
            # Security: Ensure just a filename, no paths
            safe_name = os.path.basename(req.input_filename)
            input_path = os.path.join(OUTPUT_DIR, req.job_id, safe_name)
            filename = safe_name
        else:
            # Fallback to original clip
            clip = job['result']['clips'][req.clip_index]
            filename = clip['video_url'].split('/')[-1]
            input_path = os.path.join(OUTPUT_DIR, req.job_id, filename)
        
        if not os.path.exists(input_path):
             raise HTTPException(status_code=404, detail=f"Video file not found: {input_path}")

        # Define output path for edited video
        edited_filename = f"edited_{filename}"
        output_path = os.path.join(OUTPUT_DIR, req.job_id, edited_filename)
        
        # Run editing in a thread to avoid blocking main loop
        def run_edit():
            editor = VideoEditor(api_key=final_api_key)
            
            # SAFE FILE RENAMING STRATEGY
            safe_filename = f"temp_input_{req.job_id}.mp4"
            safe_input_path = os.path.join(OUTPUT_DIR, req.job_id, safe_filename)
            
            shutil.copy(input_path, safe_input_path)
            
            try:
                vid_file = editor.upload_video(safe_input_path)
                
                import cv2
                cap = cv2.VideoCapture(safe_input_path)
                fps = cap.get(cv2.CAP_PROP_FPS)
                frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                duration = frame_count / fps if fps else 0
                cap.release()
                
                transcript = None
                try:
                    meta_files = glob.glob(os.path.join(OUTPUT_DIR, req.job_id, "*_metadata.json"))
                    if meta_files:
                        with open(meta_files[0], 'r') as f:
                            data = json.load(f)
                            transcript = data.get('transcript')
                except Exception as e:
                    print(f"⚠️ Could not load transcript for editing context: {e}")

                filter_data = editor.get_ffmpeg_filter(vid_file, duration, fps=fps, width=width, height=height, transcript=transcript)
                
                safe_output_path = os.path.join(OUTPUT_DIR, req.job_id, f"temp_output_{req.job_id}.mp4")
                editor.apply_edits(safe_input_path, safe_output_path, filter_data)
                
                if os.path.exists(safe_output_path):
                    shutil.move(safe_output_path, output_path)
                
                return filter_data
            finally:
                if os.path.exists(safe_input_path):
                    os.remove(safe_input_path)

        # Run in thread pool
        loop = asyncio.get_event_loop()
        plan = await loop.run_in_executor(None, run_edit)
        
        new_video_url = f"/videos/{req.job_id}/{edited_filename}"
        
        return {
            "success": True, 
            "new_video_url": new_video_url,
            "edit_plan": plan
        }

    except Exception as e:
        print(f"❌ Edit Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

class SubtitleRequest(BaseModel):
    job_id: str
    clip_index: int
    position: str = "bottom" 
    font_size: int = 16
    font_name: str = "Verdana"
    font_color: str = "#FFFFFF"
    border_color: str = "#000000"
    border_width: int = 2
    bg_color: str = "#000000"
    bg_opacity: float = 0.0
    input_filename: Optional[str] = None

@app.post("/api/subtitle")
async def add_subtitles(req: SubtitleRequest):
    if req.job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job = jobs[req.job_id]
    output_dir = os.path.join(OUTPUT_DIR, req.job_id)
    json_files = glob.glob(os.path.join(output_dir, "*_metadata.json"))
    
    if not json_files:
        raise HTTPException(status_code=404, detail="Metadata not found")
        
    with open(json_files[0], 'r') as f:
        data = json.load(f)
        
    transcript = data.get('transcript')
    if not transcript:
        raise HTTPException(status_code=400, detail="Transcript not found in metadata.")
        
    clips = data.get('shorts', [])
    if req.clip_index >= len(clips):
        raise HTTPException(status_code=404, detail="Clip not found")
        
    clip_data = clips[req.clip_index]
    
    if req.input_filename:
        filename = os.path.basename(req.input_filename)
    else:
        filename = clip_data.get('video_url', '').split('/')[-1]
        if not filename:
             base_name = os.path.basename(json_files[0]).replace('_metadata.json', '')
             filename = f"{base_name}_clip_{req.clip_index+1}.mp4"
         
    input_path = os.path.join(output_dir, filename)
    if not os.path.exists(input_path):
        raise HTTPException(status_code=404, detail=f"Video file not found: {input_path}")
        
    srt_filename = f"subs_{req.clip_index}_{int(time.time())}.srt"
    srt_path = os.path.join(output_dir, srt_filename)
    
    output_filename = f"subtitled_{filename}"
    output_path = os.path.join(output_dir, output_filename)
    
    try:
        success = generate_srt(transcript, clip_data['start'], clip_data['end'], srt_path)

        if not success:
             raise HTTPException(status_code=400, detail="No words found for this clip range.")

        def run_burn():
             burn_subtitles(input_path, srt_path, output_path,
                           alignment=req.position, fontsize=req.font_size,
                           font_name=req.font_name, font_color=req.font_color,
                           border_color=req.border_color, border_width=req.border_width,
                           bg_color=req.bg_color, bg_opacity=req.bg_opacity)
        
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, run_burn)
        
    except Exception as e:
        print(f"❌ Subtitle Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
        
    if req.clip_index < len(job['result']['clips']):
         job['result']['clips'][req.clip_index]['video_url'] = f"/videos/{req.job_id}/{output_filename}"
    
    try:
        if req.clip_index < len(clips):
            clips[req.clip_index]['video_url'] = f"/videos/{req.job_id}/{output_filename}"
            data['shorts'] = clips
            with open(json_files[0], 'w') as f:
                json.dump(data, f, indent=4)
    except Exception as e:
        print(f"⚠️ Failed to update metadata.json: {e}")

    return {
        "success": True,
        "new_video_url": f"/videos/{req.job_id}/{output_filename}"
    }

