import type { APIRoute } from 'astro';
import { llms } from './llms.txt';

export const GET: APIRoute = () => new Response(llms('llms-full.txt'), { headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
