export async function GET() {
  const key = import.meta.env.PUBLIC_INDEXNOW_KEY || 'INDEXNOW_KEY_PLACEHOLDER';
  return new Response(key, {
    headers: { 'Content-Type': 'text/plain' },
  });
}
