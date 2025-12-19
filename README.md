# OpenShorts 🚀🎬

OpenShorts is an open-source tool designed to automate the creation of viral vertical content. It transforms long YouTube videos or local files into multiple short clips optimized for **TikTok**, **Instagram Reels**, and **YouTube Shorts**.

![OpenShorts Demo](https://github.com/kamilstanuch/Autocrop-vertical/blob/main/churchil_queen_vertical_short.gif?raw=true)
*(The demo shows the smart crop process, now powered by AI clip selection)*

---

## ✨ Key Features

OpenShorts goes beyond simple cropping. It combines the power of Artificial Intelligence to understand your video and extract pure gold:

1.  **🧠 AI Virality Detection (Gemini + Whisper):**
    *   Automatically transcribes video audio using **OpenAI Whisper**.
    *   Analyzes content with **Google Gemini 1.5 Flash** to identify moments with the highest viral potential (hooks, jokes, impactful conclusions).
    *   Generates SEO-optimized titles and descriptions for social media.

2.  **✂️ Smart Cropping (Auto-Crop):**
    *   Detects people and faces using **YOLOv8** and **OpenCV**.
    *   Keeps the subject always in the center of the vertical frame (9:16).
    *   Automatically applies *letterboxing* if multiple people are detected far apart to preserve context.

3.  **⚡ Fast Processing:**
    *   Downloads YouTube videos in the best compatible quality.
    *   Performs precise cuts based on exact timestamps dictated by AI.
    *   Uses FFmpeg for efficient rendering.

---

## 🛠️ Requirements

*   **Docker** and **Docker Compose** installed on your machine.
*   A **Google Gemini API Key** (Free at [Google AI Studio](https://aistudio.google.com/app/apikey)).

---

## 🚀 Quick Start

### 1. Setup

Clone the repository and configure your API key:

```bash
# 1. Clone the repo
git clone https://github.com/your-username/OpenShorts.git
cd OpenShorts

# 2. Configure environment variables
cp .env.example .env

# 3. Edit .env and paste your GEMINI_API_KEY (must start with 'AIza...')
nano .env 
```

### 2. Run with Docker

No need to install Python or libraries on your system, everything runs in a container.

**From a YouTube video:**
The system will download the video, search for viral clips, and deliver multiple vertical files ready for upload.

```bash
docker compose run --rm autocrop -u "https://www.youtube.com/watch?v=YOUR_VIDEO_ID"
```

**From a local file:**
Place your video in the `videos/input/` folder.

```bash
docker compose run --rm autocrop -i /videos/input/my_video.mp4
```

### 3. Results

Generated clips will appear in the `videos/` folder (or wherever you specified). Additionally, you'll find a `.json` file with the viral titles and descriptions suggested by AI for each clip.

---

## ⚙️ Advanced Options

| Flag | Description |
| :--- | :--- |
| `-u`, `--url` | YouTube URL to download and process. |
| `-i`, `--input` | Path to the local video file (inside the container). |
| `-o`, `--output` | Output directory or specific filename. |
| `--keep-original` | Keeps the original downloaded video after processing. |
| `--skip-analysis` | **Classic Mode:** Skips Gemini/Whisper AI and converts the ENTIRE video to flat vertical format. |

---

## 🏗️ How It Works (Pipeline)

1.  **Download/Input**: Gets the source video in high quality.
2.  **Transcription (Whisper)**: Converts all audio to text with word-level timestamps.
3.  **Analysis (Gemini)**: AI reads the transcript and identifies the 3-15 most interesting segments, returning exact timestamps and metadata.
4.  **Extraction**: Selected segments are cut from the original video.
5.  **Vertical Conversion**: Each clip goes through the visual detection engine (YOLO) to dynamically reframe the action to 9:16 format.

---

## 🤝 Contributions

Contributions are welcome! If you have ideas to improve clip detection or cropping, feel free to open a PR.

## 📄 License

MIT License. Feel free to use it for your personal or commercial projects.
