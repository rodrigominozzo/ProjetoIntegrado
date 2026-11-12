// Barramento de eventos em memória → alimenta SSE (tempo real) do admin e do cliente.
// Em produção com várias instâncias: trocar por Redis Pub/Sub.
import { EventEmitter } from 'node:events';
export const bus = new EventEmitter();
bus.setMaxListeners(1000);

export function sse(req, res, filter) {
  res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache', Connection: 'keep-alive' });
  res.write(': ok\n\n');
  const handlers = {};
  for (const ev of ['message', 'agenda', 'conversation', 'typing']) {
    handlers[ev] = (data) => { if (filter(data)) res.write(`event: ${ev}\ndata: ${JSON.stringify(data)}\n\n`); };
    bus.on(ev, handlers[ev]);
  }
  const ping = setInterval(() => res.write(': ping\n\n'), 25000);
  req.on('close', () => { clearInterval(ping); for (const ev in handlers) bus.off(ev, handlers[ev]); });
}
