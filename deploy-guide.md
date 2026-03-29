# CinemaForge Deployment Guide 🚀

CinemaForge is a production-grade video generation pipeline with a React web portal, automated stock asset fetching, AI asset management, and YouTube integration.

## 🏗 System Architecture
- **Frontend**: React (Vite + TypeScript + Tailwind CSS)
- **Backend**: FastAPI (Python 3.12)
- **Database**: SQLite (SQLAlchemy)
- **Containerization**: Docker & Docker Compose

---

## 📋 Prerequisites
Before deploying to your Google VM, ensure you have:
1. **Google Cloud VM** (Ubuntu/Debian recommended) with Docker and Docker Compose installed.
2. **Pexels API Key**: For automated stock image fetching.
3. **YouTube API Credentials**: `client_secret.json` and a pre-authorized `yt_token.json`.
4. **Ports Open**: Ensure port `80` (Frontend) and `8001` (Backend API) are open in your VM's firewall.

---

## 🚀 Deployment Steps

### 1. Clone & Prepare
Clone the repository to your VM and navigate to the root directory.

```bash
git clone <your-repo-url>
cd _Director
```

### 2. Configuration
Create a `.env` file based on the provided example.

```bash
cp .env.example .env
nano .env
```

**Fill in the following:**
- `PEXELS_API_KEY`: Your key from pexels.com.
- `CINEMA_USER` / `CINEMA_PASSWORD`: For portal login.
- `VITE_API_BASE`: Set this to `http://<your-vm-ip>:8001`.

### 3. YouTube Credentials
Place your YouTube credential files in the root directory:
- `_Director/client_secret.json`
- `_Director/data/yt_token.json` (Create the `data` folder if it doesn't exist)

### 4. Build and Launch
Use Docker Compose to build and start the entire stack.

```bash
docker-compose up --build -d
```

---

## 📁 Directory Structure (Managed by Docker)
The following folders will be created automatically in the root:
- `data/`: SQLite database and YouTube tokens.
- `assets/`: Downloaded stock images and user-uploaded AI assets.
- `voices/`: Character reference audio files (.wav).
- `music/`: Drop your `.mp3` background tracks here.
- `sfx/`: Drop your `.mp3` sound effects here.
- `output_cinema/`: Final rendered video productions.

---

## 🛠 Troubleshooting
- **Logs**: View real-time logs for the backend or frontend:
  ```bash
  docker-compose logs -f backend
  docker-compose logs -f frontend
  ```
- **Permissions**: If Docker has trouble creating folders, ensure the current user has correct permissions:
  ```bash
  sudo chown -R $USER:$USER .
  ```
- **Rebuilding**: After making changes to the code or `.env`, rebuild the containers:
  ```bash
  docker-compose down
  docker-compose up --build -d
  ```

---

## 🎥 Usage Flow
1. **Login**: Access the portal at `http://<your-vm-ip>`.
2. **Script**: Paste your production script in the editor.
3. **Assets**: Review auto-fetched stock images. Upload AI videos/images for specific scenes.
4. **Voices**: Use the **Voice Registry** to upload `.wav` reference files. Assign these saved voices to detected characters in your script.
5. **Production**: Click **Start Production** once all assets are ready.
6. **Publish**: Preview the result and click **Upload to YouTube** to publish.
