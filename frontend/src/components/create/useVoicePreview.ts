import { useEffect, useRef, useState } from 'react';

/** Only one preview plays at a time across all pickers and speaker rows. */
let currentPreview: HTMLAudioElement | null = null;

/** Plays voice samples; `playing` is the URL being played. */
export const useVoicePreview = () => {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [playing, setPlaying] = useState<string | null>(null);

  useEffect(
    () => () => {
      audioRef.current?.pause();
    },
    [],
  );

  const stop = () => {
    audioRef.current?.pause();
    audioRef.current = null;
    setPlaying(null);
  };

  const toggle = (url: string | null) => {
    if (!url) return;
    if (playing === url) {
      stop();
      return;
    }
    currentPreview?.pause();
    audioRef.current?.pause();
    const audio = new Audio(url);
    const ended = () => setPlaying((p) => (p === url ? null : p));
    audio.onpause = ended;
    audio.onended = ended;
    audio.onerror = ended;
    audioRef.current = audio;
    currentPreview = audio;
    audio
      .play()
      .then(() => setPlaying(url))
      .catch(ended);
  };

  return { playing, toggle };
};
