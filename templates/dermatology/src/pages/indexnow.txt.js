// IndexNow key file — the deploy pipeline renames this to {key}.txt
export async function GET() {
  const key = import.meta.env.PUBLIC_INDEXNOW_KEY || '';
  return new Response(key, {
    headers: { 'Content-Type': 'text/plain' }
  });
}
