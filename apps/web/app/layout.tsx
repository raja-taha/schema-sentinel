import type { Metadata } from "next";
import { IBM_Plex_Mono, Outfit } from "next/font/google";
import "./globals.css";

const outfit = Outfit({
  subsets: ["latin"],
  variable: "--font-outfit",
});

const plex = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-plex",
});

export const metadata: Metadata = {
  title: "SchemaSentinel — Migration Risk Analyzer",
  description:
    "Parse SQL/ORM migrations, score lock and data-loss risk, map blast radius, and ship safer rollouts.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={`${outfit.variable} ${plex.variable} font-display antialiased`}>
        <div className="relative min-h-screen">
          <div className="pointer-events-none absolute inset-0 grid-fade" />
          <div className="relative z-10">{children}</div>
        </div>
      </body>
    </html>
  );
}
