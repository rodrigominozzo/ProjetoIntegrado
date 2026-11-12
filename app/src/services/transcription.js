// Transcrição de áudio (speech-to-text).
// Ordem: 1) OpenAI Whisper/gpt-4o-transcribe se OPENAI_API_KEY; 2) transcrição feita no navegador
// (Web Speech API do simulador); 3) marcador para a equipe ouvir.
export async function transcribe(audio, clientTranscript) {
  if (process.env.OPENAI_API_KEY && audio?.b64) {
    try {
      const form = new FormData();
      const ext = (audio.mime || 'audio/ogg').includes('webm') ? 'webm' : (audio.mime || '').includes('mp4') ? 'm4a' : 'ogg';
      form.append('file', new Blob([Buffer.from(audio.b64, 'base64')], { type: audio.mime || 'audio/ogg' }), `audio.${ext}`);
      form.append('model', process.env.TRANSCRIBE_MODEL || 'whisper-1');
      form.append('language', 'pt');
      const r = await fetch('https://api.openai.com/v1/audio/transcriptions', { method: 'POST', headers: { Authorization: `Bearer ${process.env.OPENAI_API_KEY}` }, body: form });
      if (r.ok) return (await r.json()).text;
      console.error('[transcrição]', r.status, await r.text());
    } catch (e) { console.error('[transcrição]', e.message); }
  }
  if (clientTranscript?.trim()) return clientTranscript.trim();
  return '[áudio recebido — transcrição indisponível]';
}
