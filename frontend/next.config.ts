import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Static export for S3 + CloudFront hosting.
  // Client-side auth guards (useEffect in layout.tsx) replace middleware.
  output: "export",
  // Disable Next.js image optimization (not supported in static export).
  // Use regular <img> tags or a CDN-based image service instead.
  images: { unoptimized: true },
  reactCompiler: true,
};

export default nextConfig;
