import type { MetadataRoute } from "next";

// Lets the owner "Add to Home Screen" on Android/iOS until the native app ships.
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Workforce OS",
    short_name: "Workforce",
    description: "Your AI workforce command center",
    start_url: "/",
    display: "standalone",
    background_color: "#f6f7fb",
    theme_color: "#14213d",
    icons: [{ src: "/icon.svg", sizes: "any", type: "image/svg+xml" }],
  };
}
