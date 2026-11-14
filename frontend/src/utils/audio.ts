/**
 * Small browser audio helpers for teacher voice-clone recording.
 *
 * MediaRecorder usually produces WebM/Opus, whose duration is hard to measure
 * reliably. We decode the recording and re-encode it as 16 kHz mono WAV so the
 * backend can validate the exact duration and the provider receives a WAV file.
 */

function writeString(view: DataView, offset: number, str: string) {
  for (let i = 0; i < str.length; i++) {
    view.setUint8(offset + i, str.charCodeAt(i));
  }
}

function downsampleBuffer(buffer: Float32Array, inputRate: number, outputRate: number): Float32Array {
  if (inputRate === outputRate) return buffer;
  const ratio = inputRate / outputRate;
  const newLength = Math.round(buffer.length / ratio);
  const result = new Float32Array(newLength);
  let offsetResult = 0;
  let offsetBuffer = 0;
  while (offsetResult < result.length) {
    const nextOffset = Math.round((offsetResult + 1) * ratio);
    let accum = 0;
    let count = 0;
    for (let i = offsetBuffer; i < nextOffset && i < buffer.length; i++) {
      accum += buffer[i];
      count++;
    }
    result[offsetResult] = count > 0 ? accum / count : 0;
    offsetResult++;
    offsetBuffer = nextOffset;
  }
  return result;
}

function encodeWAV(samples: Float32Array, sampleRate: number): Blob {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  writeString(view, 0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  writeString(view, 8, "WAVE");
  writeString(view, 12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeString(view, 36, "data");
  view.setUint32(40, samples.length * 2, true);
  let offset = 44;
  for (let i = 0; i < samples.length; i++, offset += 2) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Blob([view], { type: "audio/wav" });
}

/** Decode any recorded blob and return a 16 kHz mono WAV blob (or the original on failure). */
export async function blobToWav(blob: Blob, targetRate = 16000): Promise<Blob> {
  const AudioContextClass: any = window.AudioContext || (window as any).webkitAudioContext;
  if (!AudioContextClass) return blob;

  const arrayBuffer = await blob.arrayBuffer();
  const ctx = new AudioContextClass();
  try {
    const decoded = await ctx.decodeAudioData(arrayBuffer.slice(0));
    const merged = decoded.getChannelData(0);
    const downsampled = downsampleBuffer(merged, decoded.sampleRate, targetRate);
    return encodeWAV(downsampled, targetRate);
  } catch {
    return blob;
  } finally {
    if (ctx.close) await ctx.close().catch(() => {});
  }
}
