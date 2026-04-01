import React from 'react';
import { Sparkles, Scissors, Subtitles, Youtube, Instagram, Shield, Github, ArrowRight, Check, ChevronDown, Type, Upload } from 'lucide-react';

const TikTokIcon = ({ size = 16, className = "" }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" className={className}>
    <path d="M19.589 6.686a4.793 4.793 0 0 1-3.77-4.245V2h-3.445v13.672a2.896 2.896 0 0 1-5.201 1.743l-.002-.001.002.001a2.895 2.895 0 0 1 3.183-4.51v-3.5a6.329 6.329 0 0 0-5.394 10.692 6.33 6.33 0 0 0 10.857-4.424V8.687a8.182 8.182 0 0 0 4.773 1.526V6.79a4.831 4.831 0 0 1-1.003-.104z" />
  </svg>
);

const FeatureCard = ({ icon: Icon, title, description }) => (
  <div className="group bg-surface/50 backdrop-blur-xl border border-white/10 rounded-2xl p-6 hover:border-primary/30 transition-all duration-300 hover:shadow-lg hover:shadow-primary/5">
    <div className="w-12 h-12 rounded-xl bg-primary/10 flex items-center justify-center mb-4 group-hover:bg-primary/20 transition-colors">
      <Icon size={24} className="text-primary" />
    </div>
    <h3 className="text-lg font-semibold text-white mb-2">{title}</h3>
    <p className="text-zinc-400 text-sm leading-relaxed">{description}</p>
  </div>
);

const StepCard = ({ number, title, description }) => (
  <div className="flex gap-4">
    <div className="flex-shrink-0 w-10 h-10 rounded-full bg-primary/20 border border-primary/30 flex items-center justify-center text-primary font-bold text-sm">
      {number}
    </div>
    <div>
      <h3 className="text-white font-semibold mb-1">{title}</h3>
      <p className="text-zinc-400 text-sm leading-relaxed">{description}</p>
    </div>
  </div>
);

const ComparisonRow = ({ feature, openshorts, opusclip, kapwing }) => (
  <tr className="border-b border-white/5">
    <td className="py-3 px-4 text-sm text-zinc-300">{feature}</td>
    <td className="py-3 px-4 text-center">{openshorts}</td>
    <td className="py-3 px-4 text-center">{opusclip}</td>
    <td className="py-3 px-4 text-center">{kapwing}</td>
  </tr>
);

const FAQItem = ({ question, answer, isOpen, onClick }) => (
  <div className="border border-white/10 rounded-xl overflow-hidden">
    <button
      onClick={onClick}
      className="w-full flex items-center justify-between px-6 py-4 text-left hover:bg-white/5 transition-colors"
    >
      <span className="text-white font-medium pr-4">{question}</span>
      <ChevronDown size={18} className={`text-zinc-400 flex-shrink-0 transition-transform ${isOpen ? 'rotate-180' : ''}`} />
    </button>
    {isOpen && (
      <div className="px-6 pb-5">
        <p className="faq-answer text-zinc-400 text-sm leading-relaxed">{answer}</p>
      </div>
    )}
  </div>
);

export default function Landing({ onLaunchApp }) {
  const [openFaq, setOpenFaq] = React.useState(null);

  const features = [
    {
      icon: Sparkles,
      title: "AI Viral Moment Detection",
      description: "Google Gemini 1.5 Flash analyzes your video transcript and scene boundaries to detect the 3-15 most engaging moments. Each clip is scored for viral potential based on emotional impact, hook strength, and shareability."
    },
    {
      icon: Scissors,
      title: "Smart 9:16 Vertical Cropping",
      description: "AI reframing: follows subjects with MediaPipe face detection + YOLOv8 fallback. GENERAL mode creates blurred backgrounds for group shots and landscapes."
    },
    {
      icon: Subtitles,
      title: "Automatic Subtitle Generation",
      description: "Powered by faster-whisper with word-level timestamps. Subtitles are auto-generated, styled, and burned into your clips to increase engagement."
    },
    {
      icon: Type,
      title: "Hook Text Overlays",
      description: "Add attention-grabbing text overlays with styled fonts. AI-generated hook titles capture viewers in the first 3 seconds — critical for TikTok and Reels engagement."
    },
    {
      icon: Upload,
      title: "YouTube URL or Local Upload",
      description: "Paste any YouTube URL or upload a local video file. yt-dlp handles downloads at maximum quality while preserving original resolution and audio."
    },
    {
      icon: Shield,
      title: "100% Self-Hosted & Private",
      description: "Deploy with Docker on your own machine. Your videos never leave your infrastructure. API keys are managed client-side and stored securely on your server."
    }
  ];

  const steps = [
    { title: "Paste a YouTube URL or Upload a Video", description: "Drop any YouTube link or upload a local video file. ClippyMe supports all common formats and resolutions." },
    { title: "AI Detects the Best Viral Moments", description: "Google Gemini transcribes, analyzes scene boundaries, and identifies high-potential clips." },
    { title: "Smart Cropping to Vertical 9:16", description: "AI reframes each clip to vertical format with face tracking. Subjects stay centered with stabilized camera movement." },
    { title: "Add Subtitles & Effects", description: "Auto-generate styled subtitles and apply AI-driven vertical reframing." },
    { title: "Download and Share", description: "Export your viral-ready clips directly from the dashboard." }
  ];

  const faqs = [
    {
      question: "What is ClippyMe and how does it work?",
      answer: "ClippyMe is a free, open source AI clip generator that transforms long YouTube videos or local uploads into viral-ready short clips in 9:16 vertical format. It uses a multi-step AI pipeline: faster-whisper for transcription, PySceneDetect for scene detection, and Google Gemini AI for identifying the most engaging viral moments."
    },
    {
      question: "Is ClippyMe really free? What's the catch?",
      answer: "ClippyMe is 100% free and open source. You self-host it using Docker on your own machine. It uses the Google Gemini API (required) which offers a generous free tier of 1,500 requests per day. There are no watermarks, no usage limits, and no monthly subscriptions."
    },
    {
      question: "How does it compare to Opus Clip?",
      answer: "ClippyMe is a free, self-hosted alternative to Opus Clip. Both offer AI viral moment detection and smart vertical cropping. ClippyMe runs on your own infrastructure for full data privacy and has no recurring costs."
    },
    {
      question: "How do I convert a YouTube video to TikTok or Reels?",
      answer: "Simply paste the YouTube URL into ClippyMe, enter your Gemini API key, and click Process. The AI automatically downloads the video, transcribes it, detects the best moments, and crops them to 9:16 vertical format with face tracking."
    }
  ];

  const checkIcon = <Check size={16} className="text-green-400 mx-auto" />;
  const xIcon = <span className="text-zinc-500 text-sm">Paid</span>;

  return (
    <div className="min-h-screen bg-background text-white">
      {/* Navigation */}
      <nav className="fixed top-0 w-full z-50 bg-background/80 backdrop-blur-xl border-b border-white/5">
        <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <img src="/logo-openshorts.png" alt="ClippyMe logo" className="w-8 h-8" />
            <span className="text-lg font-bold">ClippyMe</span>
          </div>
          <div className="hidden md:flex items-center gap-8 text-sm text-zinc-400">
            <a href="#features" className="hover:text-white transition-colors">Features</a>
            <a href="#how-it-works" className="hover:text-white transition-colors">How It Works</a>
            <a href="#comparison" className="hover:text-white transition-colors">Comparison</a>
            <a href="#faq" className="hover:text-white transition-colors">FAQ</a>
          </div>
          <div className="flex items-center gap-3">
            <a
              href="https://github.com/fralapo/clippyme"
              target="_blank"
              rel="noopener noreferrer"
              className="hidden sm:flex items-center gap-2 text-sm text-zinc-400 hover:text-white transition-colors"
            >
              <Github size={18} />
              <span>GitHub</span>
            </a>
            <button
              onClick={onLaunchApp}
              className="bg-primary hover:bg-blue-600 text-white px-5 py-2 rounded-xl text-sm font-medium transition-all active:scale-[0.98] shadow-lg shadow-primary/20"
            >
              Launch App
            </button>
          </div>
        </div>
      </nav>

      {/* Hero Section */}
      <section className="pt-32 pb-20 px-6">
        <div className="max-w-5xl mx-auto text-center">
          <div className="inline-flex items-center gap-2 bg-primary/10 border border-primary/20 rounded-full px-4 py-1.5 text-sm text-primary mb-8">
            <Sparkles size={14} />
            <span>Free & Open Source AI Clip Generator</span>
          </div>

          <h1 className="text-4xl md:text-6xl lg:text-7xl font-bold leading-tight mb-6 tracking-tight">
            Free Open Source
            <span className="bg-gradient-to-r from-primary via-purple-400 to-pink-500 bg-clip-text text-transparent"> AI Clip Generator </span>
          </h1>

          <p className="hero-description text-lg md:text-xl text-zinc-400 max-w-3xl mx-auto mb-10 leading-relaxed">
            Turn long YouTube videos into viral shorts with AI moment detection, smart 9:16 vertical crop, and automatic subtitles. Self-hosted, open source, no limits.
          </p>

          <div className="flex flex-col sm:flex-row items-center justify-center gap-4 mb-12">
            <button
              onClick={onLaunchApp}
              className="flex items-center gap-2 bg-primary hover:bg-blue-600 text-white px-8 py-3.5 rounded-xl font-medium transition-all active:scale-[0.98] shadow-lg shadow-primary/20 text-lg"
            >
              Get Started Free
              <ArrowRight size={20} />
            </button>
            <a
              href="https://github.com/fralapo/clippyme"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 bg-white/5 border border-white/10 text-white px-8 py-3.5 rounded-xl font-medium transition-all hover:bg-white/10 text-lg"
            >
              <Github size={20} />
              View on GitHub
            </a>
          </div>

          {/* Platform Icons */}
          <div className="flex items-center justify-center gap-6 text-zinc-500">
            <span className="text-sm">Export to:</span>
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-1.5 text-zinc-400">
                <TikTokIcon size={18} />
                <span className="text-sm">TikTok</span>
              </div>
              <div className="flex items-center gap-1.5 text-zinc-400">
                <Instagram size={18} />
                <span className="text-sm">Reels</span>
              </div>
              <div className="flex items-center gap-1.5 text-zinc-400">
                <Youtube size={18} />
                <span className="text-sm">Shorts</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Stats Bar */}
      <section className="border-y border-white/5 bg-surface/30">
        <div className="max-w-5xl mx-auto px-6 py-10 grid grid-cols-2 md:grid-cols-4 gap-8 text-center">
          <div>
            <div className="text-3xl font-bold text-white">100%</div>
            <div className="text-sm text-zinc-400 mt-1">Free & Open Source</div>
          </div>
          <div>
            <div className="text-3xl font-bold text-white">AI</div>
            <div className="text-sm text-zinc-400 mt-1">Moment Detection</div>
          </div>
          <div>
            <div className="text-3xl font-bold text-white">9:16</div>
            <div className="text-sm text-zinc-400 mt-1">Smart Vertical Crop</div>
          </div>
          <div>
            <div className="text-3xl font-bold text-white">$0</div>
            <div className="text-sm text-zinc-400 mt-1">No Watermarks</div>
          </div>
        </div>
      </section>

      {/* Features Section */}
      <section id="features" className="py-20 px-6">
        <div className="max-w-6xl mx-auto">
          <div className="text-center mb-14">
            <h2 className="text-3xl md:text-4xl font-bold mb-4">Powerful Features for Viral Content</h2>
            <p className="text-zinc-400 max-w-2xl mx-auto">Clip long videos into shorts with AI moment detection and smart vertical reframing.</p>
          </div>
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-5">
            {features.map((feature, i) => (
              <FeatureCard key={i} {...feature} />
            ))}
          </div>
        </div>
      </section>

      {/* How It Works Section */}
      <section id="how-it-works" className="py-20 px-6 bg-surface/20">
        <div className="max-w-4xl mx-auto">
          <div className="text-center mb-14">
            <h2 className="text-3xl md:text-4xl font-bold mb-4">How It Works</h2>
            <p className="text-zinc-400 max-w-2xl mx-auto">From a YouTube URL to viral-ready clips in automated steps. The entire pipeline runs on your machine.</p>
          </div>
          <div className="space-y-8">
            {steps.map((step, i) => (
              <StepCard key={i} number={i + 1} {...step} />
            ))}
          </div>
        </div>
      </section>

      {/* Tech Stack */}
      <section className="py-20 px-6">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-14">
            <h2 className="text-3xl md:text-4xl font-bold mb-4">Built with Proven Technology</h2>
            <p className="text-zinc-400 max-w-2xl mx-auto">ClippyMe combines industry-leading AI models and open source tools.</p>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {[
              { name: "Google Gemini 1.5", desc: "AI Analysis" },
              { name: "faster-whisper", desc: "Transcription" },
              { name: "YOLOv8", desc: "Object Detection" },
              { name: "MediaPipe", desc: "Face Tracking" },
              { name: "FFmpeg", desc: "Video Processing" },
              { name: "React + Vite", desc: "Dashboard" },
              { name: "Docker", desc: "Deployment" }
            ].map((tech, i) => (
              <div key={i} className="bg-surface/50 border border-white/10 rounded-xl p-4 text-center">
                <div className="text-white font-medium text-sm">{tech.name}</div>
                <div className="text-zinc-500 text-xs mt-1">{tech.desc}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Comparison Table */}
      <section id="comparison" className="py-20 px-6 bg-surface/20">
        <div className="max-w-4xl mx-auto">
          <div className="text-center mb-14">
            <h2 className="text-3xl md:text-4xl font-bold mb-4">Free Clip Generator vs Paid Alternatives</h2>
            <p className="text-zinc-400 max-w-2xl mx-auto">Why pay $15-228/month for an AI clip generator when you can self-host the same capabilities for free?</p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-white/10">
                  <th className="py-3 px-4 text-left text-sm text-zinc-400 font-medium">Feature</th>
                  <th className="py-3 px-4 text-center text-sm font-medium">
                    <span className="text-primary">ClippyMe</span>
                  </th>
                  <th className="py-3 px-4 text-center text-sm text-zinc-400 font-medium">Opus Clip</th>
                  <th className="py-3 px-4 text-center text-sm text-zinc-400 font-medium">Kapwing</th>
                </tr>
              </thead>
              <tbody>
                <ComparisonRow feature="Price" openshorts={<span className="text-green-400 font-semibold">$0 Free</span>} opusclip={xIcon} kapwing={xIcon} />
                <ComparisonRow feature="AI Viral Moment Detection" openshorts={checkIcon} opusclip={checkIcon} kapwing={checkIcon} />
                <ComparisonRow feature="Smart Vertical Cropping" openshorts={checkIcon} opusclip={checkIcon} kapwing={checkIcon} />
                <ComparisonRow feature="Auto Subtitles" openshorts={checkIcon} opusclip={checkIcon} kapwing={checkIcon} />
                <ComparisonRow feature="Hook Text Overlays" openshorts={checkIcon} opusclip={checkIcon} kapwing={checkIcon} />
                <ComparisonRow feature="Self-Hosted / Privacy" openshorts={checkIcon} opusclip={<span className="text-zinc-500 text-sm">Cloud only</span>} kapwing={<span className="text-zinc-500 text-sm">Cloud only</span>} />
                <ComparisonRow feature="No Watermark" openshorts={checkIcon} opusclip={<span className="text-zinc-500 text-sm">Free tier only</span>} kapwing={<span className="text-zinc-500 text-sm">Paid</span>} />
                <ComparisonRow feature="Open Source" openshorts={checkIcon} opusclip={<span className="text-zinc-500 text-sm">No</span>} kapwing={<span className="text-zinc-500 text-sm">No</span>} />
                <ComparisonRow feature="Usage Limits" openshorts={<span className="text-green-400 text-sm">Unlimited</span>} opusclip={<span className="text-zinc-500 text-sm">Per plan</span>} kapwing={<span className="text-zinc-500 text-sm">Per plan</span>} />
              </tbody>
            </table>
          </div>
        </div>
      </section>

      {/* FAQ Section */}
      <section id="faq" className="py-20 px-6">
        <div className="max-w-3xl mx-auto">
          <div className="text-center mb-14">
            <h2 className="text-3xl md:text-4xl font-bold mb-4">Frequently Asked Questions</h2>
            <p className="text-zinc-400">Everything you need to know about ClippyMe.</p>
          </div>
          <div className="space-y-3">
            {faqs.map((faq, i) => (
              <FAQItem
                key={i}
                question={faq.question}
                answer={faq.answer}
                isOpen={openFaq === i}
                onClick={() => setOpenFaq(openFaq === i ? null : i)}
              />
            ))}
          </div>
        </div>
      </section>

      {/* CTA Section */}
      <section className="py-20 px-6 bg-surface/20">
        <div className="max-w-3xl mx-auto text-center">
          <h2 className="text-3xl md:text-4xl font-bold mb-4">Start Creating Viral Videos for Free</h2>
          <p className="text-zinc-400 mb-8 max-w-xl mx-auto">No sign-up, no credit card, no watermarks. Generate viral clips from long videos. Self-host with Docker.</p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
            <button
              onClick={onLaunchApp}
              className="flex items-center gap-2 bg-primary hover:bg-blue-600 text-white px-8 py-3.5 rounded-xl font-medium transition-all active:scale-[0.98] shadow-lg shadow-primary/20 text-lg"
            >
              Launch ClippyMe
              <ArrowRight size={20} />
            </button>
            <a
              href="https://github.com/fralapo/clippyme"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 text-zinc-400 hover:text-white transition-colors text-sm"
            >
              <Github size={18} />
              Star on GitHub
            </a>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-white/5 py-10 px-6">
        <div className="max-w-5xl mx-auto flex flex-col md:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <img src="/logo-openshorts.png" alt="ClippyMe" className="w-6 h-6" />
            <span className="text-sm text-zinc-400">ClippyMe — Free Open Source AI Clip Generator</span>
          </div>
          <div className="flex items-center gap-6 text-sm text-zinc-500">
            <a href="https://github.com/fralapo/clippyme" target="_blank" rel="noopener noreferrer" className="hover:text-white transition-colors">GitHub</a>
            <a href="#features" className="hover:text-white transition-colors">Features</a>
            <a href="#faq" className="hover:text-white transition-colors">FAQ</a>
          </div>
        </div>
      </footer>
    </div>
  );
}
