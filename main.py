import os
import shutil
import asyncio
import uvicorn
from fastapi import FastAPI, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pyngrok import ngrok

# Import our pipeline modules
from app.audio_pipeline import clone_voice
from app.video_pipeline import generate_scene
from app.sync_pipeline import sync_lips

app = FastAPI(title="NeuralCut AI Backend")

# CORS is CRITICAL: Allows your Vercel frontend to talk to this Ngrok backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict this to your Vercel URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount the static folder so we can serve the dummy video back to the frontend
os.makedirs("static", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def health_check():
    return {"status": "online", "gpu": "ready", "message": "NeuralCut Backend is live!"}

@app.post("/api/generate")
async def generate_video(
    face_image: UploadFile = File(...),
    reference_audio: UploadFile = File(...),
    driving_video: UploadFile = File(None), # Optional
    prompt: str = Form(...),
    style: str = Form(...)
):
    print(f"\n🚀 NEW REQUEST RECEIVED!")
    print(f"Prompt: {prompt} | Style: {style}")
    print(f"Files: Face({face_image.filename}), Audio({reference_audio.filename})")

    # 1. Save uploaded files to a temporary directory
    temp_dir = "temp_uploads"
    os.makedirs(temp_dir, exist_ok=True)
    
    face_path = os.path.join(temp_dir, face_image.filename)
    audio_path = os.path.join(temp_dir, reference_audio.filename)
    
    with open(face_path, "wb") as buffer: shutil.copyfileobj(face_image.file, buffer)
    with open(audio_path, "wb") as buffer: shutil.copyfileobj(reference_audio.file, buffer)

    try:
        # 2. Run the Sequential AI Pipelines (Mocked for now)
        print("🎙️ Step 1: Cloning Voice...")
        cloned_audio_path = await clone_voice(audio_path)
        
        print("🎬 Step 2: Generating Scene...")
        raw_video_path = await generate_scene(face_path, prompt, style)
        
        print("👄 Step 3: Syncing Lips...")
        final_video_path = await sync_lips(raw_video_path, cloned_audio_path)

        # 3. Move final video to static folder so frontend can access it via URL
        output_filename = "latest_output.mp4"
        final_static_path = os.path.join("static", output_filename)
        shutil.copy(final_video_path, final_static_path)
        
        # Construct the public Ngrok URL for the video
        # Note: We will update this dynamically in the actual notebook
        public_url = ngrok.get_tunnels()[0].public_url if ngrok.get_tunnels() else "http://localhost:8000"
        video_url = f"{public_url}/static/{output_filename}"

        return {
            "success": True,
            "message": "Video generated successfully!",
            "video_url": video_url
        }

    except Exception as e:
        print(f"❌ ERROR: {str(e)}")
        return {"success": False, "message": str(e)}
    
    finally:
        # Clean up temp files
        shutil.rmtree(temp_dir, ignore_errors=True)

# ==========================================
# 🚀 NGROK TUNNEL & SERVER STARTUP
# ==========================================
if __name__ == "__main__":
    # 1. Setup Ngrok (Replace with your actual authtoken from dashboard.ngrok.com)
    NGROK_AUTH_TOKEN = "YOUR_NGROK_AUTH_TOKEN_HERE"
    ngrok.set_auth_token(NGROK_AUTH_TOKEN)
    
    # 2. Create a public tunnel to port 8000
    public_url = ngrok.connect(8000)
    print(f"\n" + "="*50)
    print(f"🌐 NGROK TUNNEL ACTIVE!")
    print(f"👉 FRONTEND URL TO USE: {public_url}")
    print(f"="*50 + "\n")

    # 3. Start the FastAPI server
    uvicorn.run(app, host="0.0.0.0", port=8000)
