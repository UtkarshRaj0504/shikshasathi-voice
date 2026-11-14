import React, { useEffect, useRef, useState } from "react";

interface AudioPlayerProps {
  audioBase64?: string | null;
  contentType?: string;
  isCloned?: boolean;
  fallback?: boolean;
  notice?: string | null;
  label?: string | null;
  autoPlay?: boolean;
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
}

export const AudioPlayer: React.FC<AudioPlayerProps> = ({
  audioBase64,
  contentType = "audio/wav",
  isCloned = false,
  fallback = false,
  notice,
  label,
  autoPlay = true,
  loading = false,
  error = null,
  onRetry,
}) => {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [isPlaying, setIsPlaying] = useState<boolean>(false);
  const [currentTime, setCurrentTime] = useState<number>(0);
  const [duration, setDuration] = useState<number>(0);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [playbackError, setPlaybackError] = useState<string | null>(null);

  // Convert base64 to Blob URL
  useEffect(() => {
    if (!audioBase64) {
      if (audioUrl) {
        URL.revokeObjectURL(audioUrl);
        setAudioUrl(null);
      }
      return;
    }

    try {
      const binaryString = window.atob(audioBase64);
      const len = binaryString.length;
      const bytes = new Uint8Array(len);
      for (let i = 0; i < len; i++) {
        bytes[i] = binaryString.charCodeAt(i);
      }
      const blob = new Blob([bytes], { type: contentType });
      const url = URL.createObjectURL(blob);
      setAudioUrl(url);
      setPlaybackError(null);

      return () => {
        URL.revokeObjectURL(url);
      };
    } catch (err: any) {
      console.error("Failed to decode audio base64:", err);
      setPlaybackError("Failed to decode audio data.");
    }
  }, [audioBase64, contentType]);

  // Autoplay when audio URL changes
  useEffect(() => {
    if (!audioUrl || !audioRef.current || !autoPlay) return;

    const audio = audioRef.current;
    audio.currentTime = 0;
    const playPromise = audio.play();
    if (playPromise !== undefined) {
      playPromise
        .then(() => setIsPlaying(true))
        .catch((err) => {
          console.warn("Autoplay was prevented by browser policy:", err);
          setIsPlaying(false);
        });
    }
  }, [audioUrl, autoPlay]);

  const togglePlayPause = () => {
    const audio = audioRef.current;
    if (!audio) return;

    if (isPlaying) {
      audio.pause();
      setIsPlaying(false);
    } else {
      audio
        .play()
        .then(() => setIsPlaying(true))
        .catch((err) => {
          console.error("Playback failed:", err);
          setPlaybackError("Could not play audio.");
        });
    }
  };

  const replay = () => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.currentTime = 0;
    audio
      .play()
      .then(() => setIsPlaying(true))
      .catch((err) => {
        console.error("Replay error:", err);
      });
  };

  const handleTimeUpdate = () => {
    if (audioRef.current) {
      setCurrentTime(audioRef.current.currentTime);
    }
  };

  const handleLoadedMetadata = () => {
    if (audioRef.current) {
      setDuration(audioRef.current.duration || 0);
    }
  };

  const handleEnded = () => {
    setIsPlaying(false);
    setCurrentTime(0);
  };

  const formatTime = (timeInSec: number) => {
    if (isNaN(timeInSec)) return "00:00";
    const mins = Math.floor(timeInSec / 60);
    const secs = Math.floor(timeInSec % 60);
    return `${mins.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
  };

  if (loading) {
    return (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "0.5rem",
          padding: "0.75rem 1rem",
          background: "#e7f1ff",
          color: "#0d6efd",
          borderRadius: "8px",
          border: "1px solid #b6d4fe",
          fontSize: "0.95rem",
          margin: "0.75rem 0",
        }}
      >
        <span style={{ animation: "spin 1s linear infinite" }}>⏳</span>
        <span>Synthesizing voice response with AI audio engine...</span>
      </div>
    );
  }

  if (error || playbackError) {
    return (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "0.75rem 1rem",
          background: "#f8d7da",
          color: "#842029",
          borderRadius: "8px",
          border: "1px solid #f5c2c7",
          fontSize: "0.95rem",
          margin: "0.75rem 0",
        }}
      >
        <span>⚠️ {error || playbackError}</span>
        {onRetry && (
          <button
            onClick={onRetry}
            style={{
              padding: "0.3rem 0.6rem",
              background: "#842029",
              color: "#fff",
              border: "none",
              borderRadius: "4px",
              cursor: "pointer",
              fontSize: "0.85rem",
            }}
          >
            Retry Audio
          </button>
        )}
      </div>
    );
  }

  if (!audioUrl) return null;

  return (
    <div
      style={{
        background: "#f8f9fa",
        border: "1px solid #dee2e6",
        borderRadius: "8px",
        padding: "1rem",
        margin: "0.75rem 0",
      }}
    >
      <audio
        ref={audioRef}
        src={audioUrl}
        onTimeUpdate={handleTimeUpdate}
        onLoadedMetadata={handleLoadedMetadata}
        onEnded={handleEnded}
        onError={() => setPlaybackError("Error during audio stream playback.")}
      />

      {/* Fallback Notice */}
      {fallback && (
        <div
          style={{
            background: "#fff3cd",
            color: "#664d03",
            padding: "0.5rem 0.75rem",
            borderRadius: "6px",
            fontSize: "0.85rem",
            marginBottom: "0.75rem",
            border: "1px solid #ffecb5",
          }}
        >
          ℹ️ {notice || "Teacher voice unavailable; used default voice."}
        </div>
      )}

      {/* Authorized Cloned Voice Transparency Badge */}
      {isCloned && (
        <div
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: "0.4rem",
            background: "#e8f5e9",
            color: "#2e7d32",
            padding: "0.35rem 0.75rem",
            borderRadius: "16px",
            fontSize: "0.85rem",
            fontWeight: 600,
            marginBottom: "0.75rem",
            border: "1px solid #c8e6c9",
          }}
        >
          <span>🎙️</span>
          <span>{label || "AI-generated voice, authorized by the teacher."}</span>
        </div>
      )}

      {/* Player Controls Bar */}
      <div style={{ display: "flex", alignItems: "center", gap: "0.75rem" }}>
        <button
          onClick={togglePlayPause}
          style={{
            padding: "0.5rem 1rem",
            background: isPlaying ? "#ffc107" : "#0d6efd",
            color: isPlaying ? "#000" : "#fff",
            border: "none",
            borderRadius: "6px",
            fontWeight: 600,
            cursor: "pointer",
            fontSize: "0.95rem",
            display: "flex",
            alignItems: "center",
            gap: "0.4rem",
          }}
        >
          {isPlaying ? "⏸ Pause" : "▶ Play"}
        </button>

        <button
          onClick={replay}
          style={{
            padding: "0.5rem 0.75rem",
            background: "#6c757d",
            color: "#fff",
            border: "none",
            borderRadius: "6px",
            fontWeight: 500,
            cursor: "pointer",
            fontSize: "0.9rem",
          }}
          title="Replay from start"
        >
          🔄 Replay
        </button>

        {/* Timeline Slider */}
        <input
          type="range"
          min="0"
          max={duration || 100}
          step="0.1"
          value={currentTime}
          onChange={(e) => {
            const newTime = Number(e.target.value);
            setCurrentTime(newTime);
            if (audioRef.current) {
              audioRef.current.currentTime = newTime;
            }
          }}
          style={{ flex: 1, cursor: "pointer" }}
        />

        <span style={{ fontSize: "0.85rem", color: "#666", minWidth: "85px", textAlign: "right" }}>
          {formatTime(currentTime)} / {formatTime(duration)}
        </span>
      </div>
    </div>
  );
};
