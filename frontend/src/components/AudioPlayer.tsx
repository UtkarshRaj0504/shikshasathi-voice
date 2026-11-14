import React, { useEffect, useMemo, useRef, useState } from "react";

interface AudioPlayerProps {
  audioBase64?: string | null;
  /** Ordered audio parts played as one track; later parts may arrive while playing. */
  segments?: string[];
  /** True while the remaining parts are still being generated. */
  streaming?: boolean;
  contentType?: string;
  isCloned?: boolean;
  isMock?: boolean;
  fallback?: boolean;
  notice?: string | null;
  label?: string | null;
  autoPlay?: boolean;
  loading?: boolean;
  error?: string | null;
  onRetry?: () => void;
}

function base64ToObjectUrl(base64: string, contentType: string): string {
  const binaryString = window.atob(base64);
  const len = binaryString.length;
  const bytes = new Uint8Array(len);
  for (let i = 0; i < len; i++) {
    bytes[i] = binaryString.charCodeAt(i);
  }
  return URL.createObjectURL(new Blob([bytes], { type: contentType }));
}

const SPEEDS = [1, 1.25, 1.5, 0.75];

export const AudioPlayer: React.FC<AudioPlayerProps> = ({
  audioBase64,
  segments,
  streaming = false,
  contentType = "audio/wav",
  isCloned = false,
  isMock = false,
  fallback = false,
  notice,
  label,
  autoPlay = true,
  loading = false,
  error = null,
  onRetry,
}) => {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const urlCacheRef = useRef<Map<string, string>>(new Map());
  const firstPartRef = useRef<string | null>(null);
  const wantPlayRef = useRef<boolean>(autoPlay);

  const [urls, setUrls] = useState<string[]>([]);
  const [index, setIndex] = useState<number>(0);
  const [isPlaying, setIsPlaying] = useState<boolean>(false);
  const [currentTime, setCurrentTime] = useState<number>(0);
  const [duration, setDuration] = useState<number>(0);
  const [playbackError, setPlaybackError] = useState<string | null>(null);
  const [awaitingMore, setAwaitingMore] = useState<boolean>(false);
  const [speed, setSpeed] = useState<number>(1);

  const parts = useMemo<string[]>(() => {
    if (segments && segments.length > 0) return segments;
    return audioBase64 ? [audioBase64] : [];
  }, [segments, audioBase64]);

  useEffect(() => {
    if (parts.length === 0) {
      urlCacheRef.current.forEach((url) => URL.revokeObjectURL(url));
      urlCacheRef.current = new Map();
      firstPartRef.current = null;
      setUrls([]);
      setIndex(0);
      setCurrentTime(0);
      setDuration(0);
      setIsPlaying(false);
      setAwaitingMore(false);
      return;
    }

    if (parts[0] !== firstPartRef.current) {
      urlCacheRef.current.forEach((url) => URL.revokeObjectURL(url));
      urlCacheRef.current = new Map();
      firstPartRef.current = parts[0];
      wantPlayRef.current = autoPlay;
      setIndex(0);
      setCurrentTime(0);
      setDuration(0);
      setIsPlaying(false);
      setAwaitingMore(false);
    }

    try {
      const cache = urlCacheRef.current;
      const next = parts.map((base64) => {
        let url = cache.get(base64);
        if (!url) {
          url = base64ToObjectUrl(base64, contentType);
          cache.set(base64, url);
        }
        return url;
      });
      setPlaybackError(null);
      setUrls(next);
    } catch (err) {
      console.error("Failed to decode audio base64:", err);
      setPlaybackError("Failed to decode audio data.");
    }
  }, [parts, contentType, autoPlay]);

  useEffect(() => {
    const audio = audioRef.current;
    const url = urls[index];
    if (!audio || !url) return;

    if (audio.getAttribute("src") !== url) {
      audio.src = url;
      audio.load();
    }
    if (wantPlayRef.current) {
      const playPromise = audio.play();
      if (playPromise !== undefined) {
        playPromise
          .then(() => setIsPlaying(true))
          .catch((err) => {
            console.warn("Autoplay was prevented by browser policy:", err);
            setIsPlaying(false);
          });
      }
    }
  }, [urls, index]);

  useEffect(() => {
    if (awaitingMore && index + 1 < urls.length) {
      setAwaitingMore(false);
      setIndex(index + 1);
      setCurrentTime(0);
      setDuration(0);
    }
  }, [urls, awaitingMore, index]);

  useEffect(() => {
    return () => {
      urlCacheRef.current.forEach((url) => URL.revokeObjectURL(url));
      urlCacheRef.current.clear();
    };
  }, []);

  const togglePlayPause = () => {
    const audio = audioRef.current;
    if (!audio) return;

    if (isPlaying) {
      wantPlayRef.current = false;
      audio.pause();
      setIsPlaying(false);
    } else {
      wantPlayRef.current = true;
      const url = urls[index];
      if (url && audio.getAttribute("src") !== url) {
        audio.src = url;
      }
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
    if (!audio || urls.length === 0) return;
    wantPlayRef.current = true;
    setAwaitingMore(false);
    setIndex(0);
    setCurrentTime(0);
    if (audio.getAttribute("src") !== urls[0]) {
      audio.src = urls[0];
    }
    audio.currentTime = 0;
    audio
      .play()
      .then(() => setIsPlaying(true))
      .catch((err) => {
        console.error("Replay error:", err);
      });
  };

  const handleSpeedChange = () => {
    const idx = SPEEDS.indexOf(speed);
    const next = SPEEDS[(idx + 1) % SPEEDS.length];
    setSpeed(next);
    if (audioRef.current) audioRef.current.playbackRate = next;
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
    if (index + 1 < urls.length) {
      setIndex(index + 1);
      setCurrentTime(0);
      setDuration(0);
    } else if (streaming) {
      setAwaitingMore(true);
    } else {
      setIsPlaying(false);
      setCurrentTime(0);
    }
  };

  const formatTime = (timeInSec: number) => {
    if (isNaN(timeInSec)) return "00:00";
    const mins = Math.floor(timeInSec / 60);
    const secs = Math.floor(timeInSec % 60);
    return `${mins.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
  };

  if (urls.length === 0) {
    if (loading) {
      return (
        <div className="banner banner-info">
          <span style={{ animation: "spin 1s linear infinite" }}>⏳</span>
          <span>Synthesizing voice response with AI audio engine...</span>
        </div>
      );
    }

    if (error || playbackError) {
      return (
        <div className="banner banner-danger" style={{ justifyContent: "space-between" }}>
          <span>⚠️ {error || playbackError}</span>
          {onRetry && (
            <button className="btn btn-secondary" style={{ padding: "0.3rem 0.7rem", fontSize: "0.82rem" }} onClick={onRetry}>
              Retry Audio
            </button>
          )}
        </div>
      );
    }

    return null;
  }

  const progressPct = duration ? (currentTime / duration) * 100 : 0;

  return (
    <div className="audio-player">
      <audio
        ref={audioRef}
        onTimeUpdate={handleTimeUpdate}
        onLoadedMetadata={handleLoadedMetadata}
        onEnded={handleEnded}
        onError={() => setPlaybackError("Error during audio stream playback.")}
      />

      {streaming && (
        <div data-testid="streaming-audio-notice" className="banner banner-info" style={{ marginBottom: 12 }}>
          <span style={{ animation: "spin 1s linear infinite" }}>⏳</span>
          <span>
            Playing part {index + 1} of {urls.length} — generating the rest of the answer…
          </span>
        </div>
      )}

      {fallback && (
        <div className="banner banner-warning" style={{ marginBottom: 12 }}>
          ℹ️ {notice || "Teacher voice unavailable; used default voice."}
        </div>
      )}

      {isMock && (
        <span data-testid="mock-audio-badge" className="badge badge-warning" style={{ marginRight: 8, marginBottom: 12 }}>
          🧪 mock audio (synthetic development tone)
        </span>
      )}

      {isCloned && (
        <span className="badge badge-accent" style={{ marginRight: 8, marginBottom: 12 }}>
          <span aria-hidden="true">🎙️</span>{" "}
          <span>{label || "AI-generated voice, authorized by the teacher."}</span>
        </span>
      )}

      <div className="controls">
        <button
          className="play-btn"
          onClick={togglePlayPause}
          aria-label={isPlaying ? "⏸ Pause" : "▶ Play"}
        >
          {isPlaying ? "⏸" : "▶"}
        </button>

        <button
          onClick={replay}
          className="btn btn-ghost"
          style={{ padding: "0.4rem 0.6rem" }}
          title="Replay from start"
          aria-label="Replay"
        >
          🔄
        </button>

        <div
          className="timeline"
          onClick={(e) => {
            const rect = e.currentTarget.getBoundingClientRect();
            const pct = (e.clientX - rect.left) / rect.width;
            const newTime = pct * duration;
            setCurrentTime(newTime);
            if (audioRef.current) audioRef.current.currentTime = newTime;
          }}
        >
          <div className="timeline-fill" style={{ width: `${progressPct}%` }} />
        </div>

        <span className="time">
          {formatTime(currentTime)} / {formatTime(duration)}
        </span>

        <button className="speed-btn" onClick={handleSpeedChange} title="Playback speed">
          {speed}×
        </button>
      </div>
    </div>
  );
};
