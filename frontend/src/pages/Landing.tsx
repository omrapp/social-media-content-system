import { Instagram, Youtube, Play, Globe, MapPin, Camera } from "lucide-react";
import { Link } from "react-router-dom";
import { APP_NAME, OPERATOR_NAME, SOCIAL_URLS, handleFromUrl } from "@/lib/brand";

const SOCIAL_PLATFORMS = [
  {
    platform: "Instagram",
    href: SOCIAL_URLS.instagram,
    icon: Instagram,
    color: "from-pink-500 to-orange-400",
    bg: "bg-gradient-to-br from-pink-500/10 to-orange-400/10 border-pink-500/20",
    btn: "bg-gradient-to-r from-pink-500 to-orange-400 hover:from-pink-400 hover:to-orange-300",
  },
  {
    platform: "YouTube",
    href: SOCIAL_URLS.youtube,
    icon: Youtube,
    color: "from-red-500 to-red-400",
    bg: "bg-gradient-to-br from-red-500/10 to-red-400/10 border-red-500/20",
    btn: "bg-gradient-to-r from-red-500 to-red-400 hover:from-red-400 hover:to-red-300",
  },
  {
    platform: "TikTok",
    href: SOCIAL_URLS.tiktok,
    icon: Play,
    color: "from-sky-400 to-cyan-300",
    bg: "bg-gradient-to-br from-sky-400/10 to-cyan-300/10 border-sky-400/20",
    btn: "bg-gradient-to-r from-sky-500 to-cyan-400 hover:from-sky-400 hover:to-cyan-300",
  },
];

// Only platforms with a configured URL are shown.
const SOCIAL = SOCIAL_PLATFORMS.filter((s) => s.href).map((s) => ({
  ...s,
  handle: handleFromUrl(s.href),
}));

const CATEGORIES = [
  { icon: MapPin, label: "Hidden Gems" },
  { icon: Camera, label: "Food & Culture" },
  { icon: Globe, label: "Budget Tips" },
  { icon: Play, label: "Nature & Beach" },
];

export function LandingPage() {
  return (
    <div className="min-h-screen bg-gray-950 text-white">
      {/* Nav */}
      <nav className="fixed top-0 inset-x-0 z-50 flex items-center justify-between px-6 py-4 bg-gray-950/80 backdrop-blur border-b border-white/5">
        <span className="font-bold text-lg tracking-tight">
          <span className="text-amber-400">{APP_NAME}</span>
        </span>
        <div className="flex items-center gap-4 text-sm text-gray-400">
          <a href="#categories" className="hover:text-white transition-colors">Categories</a>
          <a href="#platforms" className="hover:text-white transition-colors">Follow</a>
          <Link
            to="/login"
            className="px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 border border-white/10 text-white text-xs transition-colors"
          >
            Admin
          </Link>
        </div>
      </nav>

      {/* Hero */}
      <section className="relative pt-32 pb-24 px-6 overflow-hidden">
        {/* Gradient orbs */}
        <div className="absolute top-0 left-1/4 w-96 h-96 bg-amber-500/10 rounded-full blur-3xl pointer-events-none" />
        <div className="absolute top-20 right-1/4 w-80 h-80 bg-orange-500/10 rounded-full blur-3xl pointer-events-none" />

        <div className="relative max-w-3xl mx-auto text-center">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-amber-500/10 border border-amber-500/20 text-amber-400 text-xs font-medium mb-6">
            <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
            New episodes daily
          </div>

          <h1 className="text-5xl sm:text-6xl font-bold tracking-tight leading-tight mb-4">
            Every clip.{" "}
            <span className="bg-gradient-to-r from-amber-400 via-orange-400 to-rose-400 bg-clip-text text-transparent">
              Every platform.
            </span>
            <br />
            One reel at a time.
          </h1>

          <p className="text-gray-400 text-lg leading-relaxed max-w-xl mx-auto mb-10">
            Short-form storytelling across curated categories — food, fitness, culture, nature and
            more. New reels drop daily, so there's always a reason to come back.
          </p>

          <div className="flex flex-wrap gap-3 justify-center">
            {SOCIAL.map(({ platform, href, btn, icon: Icon }) => (
              <a
                key={platform}
                href={href}
                target="_blank"
                rel="noopener noreferrer"
                className={`inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-medium text-white transition-all ${btn}`}
              >
                <Icon size={16} />
                Follow on {platform}
              </a>
            ))}
          </div>
        </div>
      </section>

      {/* Categories */}
      <section id="categories" className="py-20 px-6 bg-white/[0.02] border-y border-white/5">
        <div className="max-w-4xl mx-auto">
          <div className="text-center mb-12">
            <h2 className="text-3xl font-bold mb-3">Built around content categories</h2>
            <p className="text-gray-400 max-w-xl mx-auto">
              Not random clips. Every reel is picked and edited to fit a category — so the feed
              stays varied and there's always a reason to come back.
            </p>
          </div>

          <div className="grid sm:grid-cols-3 gap-4 mb-10">
            {[
              {
                step: "01",
                title: "Tagged by category",
                desc: "Every clip is sorted into a category — food, fitness, culture, nature, and more.",
              },
              {
                step: "02",
                title: "Daily reels",
                desc: "New reels drop on a schedule, drawing from whichever category is performing best.",
              },
              {
                step: "03",
                title: "Always fresh",
                desc: "A rotation across categories keeps the feed varied, never repetitive.",
              },
            ].map(({ step, title, desc }) => (
              <div
                key={step}
                className="relative p-5 rounded-2xl bg-white/[0.03] border border-white/10 overflow-hidden"
              >
                <div className="absolute top-4 right-4 text-4xl font-black text-white/5 select-none">
                  {step}
                </div>
                <h3 className="font-semibold text-white mb-2">{title}</h3>
                <p className="text-gray-400 text-sm leading-relaxed">{desc}</p>
              </div>
            ))}
          </div>

          {/* Categories */}
          <div className="flex flex-wrap gap-3 justify-center">
            {CATEGORIES.map(({ icon: Icon, label }) => (
              <div
                key={label}
                className="flex items-center gap-2 px-4 py-2 rounded-full bg-white/5 border border-white/10 text-sm text-gray-300"
              >
                <Icon size={14} className="text-amber-400" />
                {label}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Platforms */}
      <section id="platforms" className="py-20 px-6">
        <div className="max-w-3xl mx-auto">
          <div className="text-center mb-12">
            <h2 className="text-3xl font-bold mb-3">Follow on every platform</h2>
            <p className="text-gray-400">New reels drop daily, with platform-native captions.</p>
          </div>

          <div className="grid sm:grid-cols-3 gap-4">
            {SOCIAL.map(({ platform, handle, href, bg, btn, icon: Icon }) => (
              <div
                key={platform}
                className={`p-5 rounded-2xl border flex flex-col gap-4 ${bg}`}
              >
                <div className="flex items-center gap-3">
                  <div className="p-2 rounded-xl bg-white/10">
                    <Icon size={18} />
                  </div>
                  <div>
                    <div className="font-semibold text-sm">{platform}</div>
                    <div className="text-gray-400 text-xs">{handle}</div>
                  </div>
                </div>
                <a
                  href={href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={`w-full flex items-center justify-center gap-2 px-4 py-2 rounded-lg text-sm font-medium text-white transition-all ${btn}`}
                >
                  Follow
                </a>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-white/5 px-6 py-8">
        <div className="max-w-4xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4 text-sm text-gray-500">
          <span>© {new Date().getFullYear()} {OPERATOR_NAME} · {APP_NAME}</span>
          <div className="flex items-center gap-6">
            <Link to="/privacy-policy" className="hover:text-gray-300 transition-colors">
              Privacy Policy
            </Link>
            <Link to="/terms" className="hover:text-gray-300 transition-colors">
              Terms of Service
            </Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
