"""
models.py — CinemaForge
SQLAlchemy models for cinema projects.
Separate DB from ReelForge (reelforge.db vs cinemaforge.db).
"""
import enum, os, logging
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Enum as SAEnum
from sqlalchemy.orm import declarative_base, sessionmaker
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.environ.get("CINEMA_DB_PATH", "data/cinemaforge.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
engine  = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
Session = sessionmaker(bind=engine)
Base    = declarative_base()


class ProjectStatus(str, enum.Enum):
    pending   = "pending"
    rendering = "rendering"
    rendered  = "rendered"
    uploading = "uploading"
    done      = "done"
    failed    = "failed"


class CinemaProject(Base):
    __tablename__ = "cinema_projects"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    project_id    = Column(String(16), nullable=False, unique=True)
    name          = Column(String(256), nullable=False)
    script_md     = Column(Text, nullable=False)
    meta_json     = Column(Text, nullable=True)
    manifest_json = Column(Text, nullable=True)

    status        = Column(SAEnum(ProjectStatus), default=ProjectStatus.pending)
    output_path   = Column(String(512), nullable=True)    # longform .mp4
    short_path    = Column(String(512), nullable=True)    # auto-generated Short .mp4
    error_msg     = Column(Text, nullable=True)

    yt_video_id_en = Column(String(64), nullable=True)
    yt_video_id_hi = Column(String(64), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def as_dict(self):
        return {
            "id":              self.id,
            "project_id":      self.project_id,
            "name":            self.name,
            "status":          self.status.value,
            "output_path":     self.output_path,
            "short_path":      self.short_path,
            "error_msg":       self.error_msg,
            "yt_video_id_en":  self.yt_video_id_en,
            "yt_video_id_hi":  self.yt_video_id_hi,
            "created_at":      self.created_at.isoformat() if self.created_at else None,
            "updated_at":      self.updated_at.isoformat() if self.updated_at else None,
        }


def init_db():
    Base.metadata.create_all(engine)
    logging.getLogger("models").info("CinemaForge DB initialised.")
