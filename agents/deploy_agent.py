"""
DeployAgent — builds the Astro site and deploys to Vercel.

Steps:
1. Archive source dir to R2 (before build, for future re-publishes)
2. Run `npm install` in build directory
3. Run `npm run build` to produce ./dist
4. Upload ./dist to Cloudflare R2 (dist archive)
5. Create / upsert a Vercel project and deploy ./dist
6. Add subdomain DNS alias on Vercel
7. Return live URL

Source archive key: sources/{clinic_id}/{site_id}.zip
Dist archive key:   builds/{clinic_id}/{site_id}.zip
"""
import asyncio, base64, shutil, structlog, zipfile
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
        _, stderr = await proc.communicate()
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
        _, stderr = await proc.communicate()
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
    # R2 archive helpers
    # ------------------------------------------------------------------

    def _source_r2_key(self, clinic_id: str, site_id: str) -> str:
        return f"sources/{clinic_id}/{site_id}.zip"

    def _dist_r2_key(self, clinic_id: str, site_id: str) -> str:
        return f"builds/{clinic_id}/{site_id}.zip"

    def _zip_source(self, source_dir: Path, archive_path: Path) -> None:
        """Zip source_dir to archive_path, excluding node_modules and dist."""
        skip = {"node_modules", "dist", ".astro"}
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in source_dir.rglob("*"):
                if any(part in skip for part in path.parts):
                    continue
                if path.is_file():
                    zf.write(path, path.relative_to(source_dir))

    async def upload_source_to_r2(
        self, source_dir: Path, clinic_id: str, site_id: str
    ) -> str:
        """
        Zip the Astro source directory (excluding node_modules/dist) and
        upload to R2. Returns the R2 key. Called before build so a clean
        source snapshot is always available for article re-publishing.
        """
        if not self.r2:
            logger.warning("r2_not_configured_source_skip")
            return ""

        archive_path = source_dir.parent / f"{site_id}-source.zip"
        try:
            await asyncio.to_thread(self._zip_source, source_dir, archive_path)
            r2_key = self._source_r2_key(clinic_id, site_id)
            with open(archive_path, "rb") as f:
                await asyncio.to_thread(
                    self.r2.put_object,
                    Bucket=settings.r2_bucket,
                    Key=r2_key,
                    Body=f,
                    ContentType="application/zip",
                )
            logger.info("source_uploaded_r2", key=r2_key,
                        size_kb=archive_path.stat().st_size // 1024)
            return r2_key
        except Exception as exc:
            # R2 unavailable or bucket missing — non-fatal, deployment continues.
            logger.warning("source_upload_r2_failed", error=str(exc))
            return ""
        finally:
            archive_path.unlink(missing_ok=True)

    async def download_source_from_r2(
        self, clinic_id: str, site_id: str, dest_dir: Path
    ) -> Path:
        """
        Download and extract the source archive from R2 into dest_dir.
        Returns dest_dir. Raises if R2 is not configured or key not found.
        """
        if not self.r2:
            raise RuntimeError("R2 not configured — cannot pull source archive")

        r2_key = self._source_r2_key(clinic_id, site_id)
        archive_path = dest_dir.parent / f"{site_id}-source-dl.zip"
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            response = await asyncio.to_thread(
                self.r2.get_object,
                Bucket=settings.r2_bucket,
                Key=r2_key,
            )
            body = await asyncio.to_thread(response["Body"].read)
            archive_path.write_bytes(body)
            await asyncio.to_thread(shutil.unpack_archive, str(archive_path), str(dest_dir))
            logger.info("source_downloaded_r2", key=r2_key, dest=str(dest_dir))
            return dest_dir
        finally:
            archive_path.unlink(missing_ok=True)

    async def upload_dist_to_r2(
        self, dist_dir: Path, clinic_id: str, site_id: str
    ) -> str:
        """Zip and upload the dist directory to R2. Returns R2 key."""
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

        r2_key = self._dist_r2_key(clinic_id, site_id)
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
    ) -> dict:
        """
        Deploy dist/ to Vercel via Files API.
        Returns { deployment_id, preview_url }.
        """
        # Collect all files. Vercel v13 deployments API accepts:
        #   text files  → plain string data (no encoding field)
        #   binary files → base64-encoded data with encoding="base64"
        TEXT_EXTS = {".html", ".css", ".js", ".mjs", ".json", ".txt",
                     ".xml", ".svg", ".map", ".ts", ".md", ".toml"}
        files = []
        for file_path in dist_dir.rglob("*"):
            if file_path.is_file():
                relative = str(file_path.relative_to(dist_dir)).replace("\\", "/")
                content = file_path.read_bytes()
                if file_path.suffix.lower() in TEXT_EXTS:
                    files.append({
                        "file": relative,
                        "data": content.decode("utf-8", errors="replace"),
                    })
                else:
                    files.append({
                        "file": relative,
                        "data": base64.b64encode(content).decode(),
                        "encoding": "base64",
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
            if not r.is_success:
                logger.error("vercel_deploy_error",
                             status=r.status_code, body=r.text[:500])
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

    async def cleanup_build_dir(self, build_dir: Path) -> None:
        """Remove the local build directory after deployment to prevent disk accumulation."""
        if build_dir.exists():
            await asyncio.to_thread(shutil.rmtree, build_dir, ignore_errors=True)
            logger.info("build_dir_cleaned", path=str(build_dir))

    async def deploy(
        self,
        build_dir: Path,
        clinic_id: str,
        site_id: str,
        subdomain: str,
    ) -> dict:
        """
        Full build + deploy flow.
        Archives source to R2 before building so re-publish is always possible.
        Returns {
            site_url, preview_url,
            vercel_project_id, vercel_deployment_id, r2_key, r2_source_key
        }
        """
        # Archive source BEFORE build (node_modules not yet present or excluded)
        r2_source_key = await self.upload_source_to_r2(build_dir, clinic_id, site_id)

        dist_dir = await self.build_site(build_dir)

        project_name = f"{settings.vercel_project_prefix}{subdomain}"

        vercel = await self.deploy_to_vercel(dist_dir, project_name)
        site_url = await self.add_vercel_domain(project_name, subdomain)
        r2_key = await self.upload_dist_to_r2(dist_dir, clinic_id, site_id)

        # Clean up local build directory after successful deploy
        await self.cleanup_build_dir(build_dir)

        return {
            "site_url": f"https://{site_url}",
            "preview_url": vercel["preview_url"],
            "vercel_project_id": vercel["project_id"],
            "vercel_deployment_id": vercel["deployment_id"],
            "r2_key": r2_key,
            "r2_source_key": r2_source_key,
        }
