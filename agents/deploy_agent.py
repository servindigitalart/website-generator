"""
DeployAgent — builds the Astro site and deploys to Vercel.

Steps:
1. Run `npm install` in build directory
2. Run `npm run build` to produce ./dist
3. Upload ./dist to Cloudflare R2 (static asset CDN)
4. Create / upsert a Vercel project and deploy ./dist
5. Add subdomain DNS alias on Vercel
6. Return live URL
"""
import asyncio, shutil, json, uuid, structlog
from pathlib import Path
from core.config import settings
import httpx, boto3

logger = structlog.get_logger()

BUILDS_DIR = Path(__file__).parent.parent / "builds"
VERCEL_API = "https://api.vercel.com"


class DeployAgent:
    def __init__(self):
        self.headers = {
            "Authorization": f"Bearer {settings.vercel_token}",
            "Content-Type": "application/json",
        }
        self.team_params = (
            {"teamId": settings.vercel_team_id}
            if settings.vercel_team_id
            else {}
        )
        self.r2 = (
            boto3.client(
                "s3",
                endpoint_url=settings.r2_endpoint,
                aws_access_key_id=settings.r2_access_key,
                aws_secret_access_key=settings.r2_secret_key,
                region_name="auto",
            )
            if settings.r2_endpoint
            else None
        )

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    async def build_site(self, build_dir: Path) -> Path:
        """Run npm install + npm run build. Returns dist directory."""
        logger.info("npm_install_start", dir=str(build_dir))
        proc = await asyncio.create_subprocess_exec(
            "npm", "install", "--prefer-offline",
            cwd=build_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"npm install failed: {stderr.decode()[:500]}"
            )

        logger.info("npm_build_start", dir=str(build_dir))
        proc = await asyncio.create_subprocess_exec(
            "npm", "run", "build",
            cwd=build_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(
                f"npm build failed: {stderr.decode()[:1000]}"
            )

        dist_dir = build_dir / "dist"
        if not dist_dir.exists():
            raise RuntimeError("Build succeeded but no dist/ directory found")

        logger.info("build_complete", dist=str(dist_dir))
        return dist_dir

    # ------------------------------------------------------------------
    # Upload to R2 (source archive for record-keeping)
    # ------------------------------------------------------------------

    async def upload_dist_to_r2(
        self, dist_dir: Path, clinic_id: str, site_id: str
    ) -> str:
        """Zip and upload the dist directory to R2. Returns R2 URL."""
        if not self.r2:
            return ""

        archive_name = f"{site_id}.zip"
        archive_path = dist_dir.parent / archive_name

        await asyncio.to_thread(
            shutil.make_archive,
            str(archive_path.with_suffix("")),
            "zip",
            str(dist_dir),
        )

        r2_key = f"builds/{clinic_id}/{archive_name}"
        with open(archive_path, "rb") as f:
            await asyncio.to_thread(
                self.r2.put_object,
                Bucket=settings.r2_bucket,
                Key=r2_key,
                Body=f,
                ContentType="application/zip",
            )

        archive_path.unlink(missing_ok=True)
        logger.info("dist_uploaded_r2", key=r2_key)
        return r2_key

    # ------------------------------------------------------------------
    # Vercel deployment
    # ------------------------------------------------------------------

    async def get_or_create_vercel_project(
        self, project_name: str
    ) -> str:
        """Get existing Vercel project ID or create a new one."""
        async with httpx.AsyncClient(timeout=30) as client:
            # Try to get existing project
            r = await client.get(
                f"{VERCEL_API}/v9/projects/{project_name}",
                headers=self.headers,
                params=self.team_params,
            )
            if r.status_code == 200:
                return r.json()["id"]

            # Create new project
            payload = {
                "name": project_name,
                "framework": None,  # Static site
                "publicSource": False,
            }
            r = await client.post(
                f"{VERCEL_API}/v10/projects",
                headers=self.headers,
                params=self.team_params,
                json=payload,
            )
            r.raise_for_status()
            project_id = r.json()["id"]
            logger.info("vercel_project_created", project=project_name)
            return project_id

    async def deploy_to_vercel(
        self,
        dist_dir: Path,
        project_name: str,
        subdomain: str,
    ) -> dict:
        """
        Deploy dist/ to Vercel via Files API.
        Returns { deployment_id, preview_url }.
        """
        # Collect all files
        files = []
        for file_path in dist_dir.rglob("*"):
            if file_path.is_file():
                relative = file_path.relative_to(dist_dir)
                content = file_path.read_bytes()
                files.append({
                    "file": str(relative).replace("\\", "/"),
                    "data": content.hex(),
                    "encoding": "hex",
                })

        project_id = await self.get_or_create_vercel_project(project_name)

        async with httpx.AsyncClient(timeout=120) as client:
            payload = {
                "name": project_name,
                "projectId": project_id,
                "files": files,
                "target": "production",
            }
            r = await client.post(
                f"{VERCEL_API}/v13/deployments",
                headers=self.headers,
                params=self.team_params,
                json=payload,
            )
            r.raise_for_status()
            dep = r.json()
            deployment_id = dep["id"]
            preview_url = f"https://{dep.get('url', '')}"
            logger.info("vercel_deployment_created",
                        id=deployment_id, url=preview_url)

        # Wait for deployment to complete (poll up to 3 minutes)
        deployment_url = await self._wait_for_deployment(deployment_id)

        return {
            "project_id": project_id,
            "deployment_id": deployment_id,
            "preview_url": deployment_url,
        }

    async def _wait_for_deployment(
        self, deployment_id: str, max_wait: int = 180
    ) -> str:
        """Poll Vercel until deployment is READY. Returns deployment URL."""
        async with httpx.AsyncClient(timeout=30) as client:
            for _ in range(max_wait // 5):
                await asyncio.sleep(5)
                r = await client.get(
                    f"{VERCEL_API}/v13/deployments/{deployment_id}",
                    headers=self.headers,
                    params=self.team_params,
                )
                if r.status_code != 200:
                    continue
                data = r.json()
                state = data.get("readyState", "")
                if state == "READY":
                    return f"https://{data.get('url', '')}"
                if state in ("ERROR", "CANCELED"):
                    raise RuntimeError(
                        f"Vercel deployment {state}: "
                        f"{data.get('errorMessage', '')}"
                    )

        raise TimeoutError(
            f"Vercel deployment {deployment_id} did not complete in "
            f"{max_wait}s"
        )

    async def add_vercel_domain(
        self, project_name: str, subdomain: str
    ) -> str:
        """
        Add <subdomain>.<base_domain> as an alias on the Vercel project.
        Returns the full domain.
        """
        full_domain = f"{subdomain}.{settings.base_domain}"
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"{VERCEL_API}/v10/projects/{project_name}/domains",
                headers=self.headers,
                params=self.team_params,
                json={"name": full_domain},
            )
            if r.status_code not in (200, 409):  # 409 = already exists
                logger.warning("vercel_domain_add_failed",
                               status=r.status_code, domain=full_domain)
            else:
                logger.info("vercel_domain_added", domain=full_domain)
        return full_domain

    # ------------------------------------------------------------------
    # Top-level deploy orchestration
    # ------------------------------------------------------------------

    async def deploy(
        self,
        build_dir: Path,
        clinic_id: str,
        site_id: str,
        subdomain: str,
    ) -> dict:
        """
        Full build + deploy flow.
        Returns {
            site_url, preview_url,
            vercel_project_id, vercel_deployment_id, r2_key
        }
        """
        dist_dir = await self.build_site(build_dir)

        project_name = f"{settings.vercel_project_prefix}{subdomain}"

        vercel = await self.deploy_to_vercel(dist_dir, project_name, subdomain)
        site_url = await self.add_vercel_domain(project_name, subdomain)
        r2_key = await self.upload_dist_to_r2(dist_dir, clinic_id, site_id)

        return {
            "site_url": f"https://{site_url}",
            "preview_url": vercel["preview_url"],
            "vercel_project_id": vercel["project_id"],
            "vercel_deployment_id": vercel["deployment_id"],
            "r2_key": r2_key,
        }
