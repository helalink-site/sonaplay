import { API } from './config';
const get = async (path) => { const r = await fetch(API + path); if (!r.ok) throw new Error('Request failed'); return r.json(); };
export const search = async (q, limit = 12) => (await get(`/search?q=${encodeURIComponent(q)}&limit=${limit}`)).tracks || [];
export const mixes = async (genre = '') => (await get(`/mixes?limit=20${genre ? '&genre=' + encodeURIComponent(genre) : ''}`)).tracks || [];
export async function streamUrl(id, isMix) {
  const r = await get(`/stream/${id}${isMix ? '?mix=1' : ''}`);
  if (!r.url) throw new Error('No stream');
  return r.url;
}
