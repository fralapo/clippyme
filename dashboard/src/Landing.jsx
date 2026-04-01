import React from 'react';
import { Sparkles, Scissors, Subtitles, Youtube, Instagram, Shield, Github, ArrowRight, Check, Type, Upload, Play, Star, Zap } from 'lucide-react';

const TikTokIcon = ({ size = 16, className = "" }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" className={className}>
    <path d="M19.589 6.686a4.793 4.793 0 0 1-3.77-4.245V2h-3.445v13.672a2.896 2.896 0 0 1-5.201 1.743l-.002-.001.002.001a2.895 2.895 0 0 1 3.183-4.51v-3.5a6.329 6.329 0 0 0-5.394 10.692 6.33 6.33 0 0 0 10.857-4.424V8.687a8.182 8.182 0 0 0 4.773 1.526V6.79a4.831 4.831 0 0 1-1.003-.104z" />
  </svg>
);

const FeatureCard = ({ icon: Icon, title, description, delay = "0s" }) => (
  <div 
    className="group glass-card p-8 hover:translate-y-[-4px] animate-fade-in"
    style={{ animationDelay: delay }}
  >
    <div className="w-14 h-14 rounded-2xl bg-primary/10 flex items-center justify-center mb-6 group-hover:bg-primary/20 transition-all duration-500 group-hover:rotate-[10deg]">
      <Icon size={28} className="text-primary" />
    </div>
    <h3 className="text-xl font-bold text-white mb-3">{title}</h3>
    <p className="text-zinc-400 text-sm leading-relaxed leading-6">{description}</p>
  </div>
);

const StepCard = ({ number, title, description }) => (
  <div className="relative pl-16 py-2 group">
    <div className="absolute left-0 top-0 w-12 h-12 rounded-2xl bg-white/5 border border-white/10 flex items-center justify-center text-white font-black text-lg group-hover:border-primary/50 group-hover:text-primary transition-all duration-500">
      {number}
    </div>
    <h3 className="text-xl font-bold text-white mb-2">{title}</h3>
    <p className="text-zinc-400 text-base leading-relaxed max-w-2xl">{description}</p>
  </div>
);

const ComparisonRow = ({ feature, clippyme, opusclip, kapwing }) => (
  <tr className="border-b border-white/5 group hover:bg-white/[0.02] transition-colors">
    <td className="py-5 px-6 text-sm font-medium text-zinc-300">{feature}</td>
    <td className="py-5 px-6 text-center font-bold text-white bg-primary/5">{clippyme}</td>
    <td className="py-5 px-6 text-center text-zinc-500">{opusclip}</td>
    <td className="py-5 px-6 text-center text-zinc-500">{kapwing}</td>
  </tr>
);

const FAQItem = ({ question, answer, isOpen, onClick }) => (
  <div className={`glass-card overflow-hidden transition-all duration-300 ${isOpen ? 'ring-1 ring-primary/30' : ''}`}>
    <button
      onClick={onClick}
      className="w-full flex items-center justify-between px-8 py-6 text-left hover:bg-white/5 transition-colors"
    >
      <span className={`text-lg font-semibold transition-colors ${isOpen ? 'text-primary' : 'text-white'}`}>{question}</span>
      <div className={`w-8 h-8 rounded-full bg-white/5 flex items-center justify-center transition-transform duration-500 ${isOpen ? 'rotate-180 bg-primary/20 text-primary' : 'text-zinc-500'}`}>
        <ChevronDown size={20} />
      </div>
    </button>
    <div className={`px-8 transition-all duration-500 ease-in-out ${isOpen ? 'max-h-96 pb-8 opacity-100' : 'max-h-0 opacity-0 overflow-hidden'}`}>
      <p className="text-zinc-400 text-base leading-relaxed border-t border-white/5 pt-6">{answer}</p>
    </div>
  </div>
);

export default function Landing({ onLaunchApp }) {
  const [openFaq, setOpenFaq] = React.useState(null);

  const features = [
    {
      icon: Sparkles,
      title: "AI Moment Analysis",
      description: "Google Gemini 2.5 Flash scans transcripts and scene changes to detect high-potential viral hooks automatically.",
      delay: "0.1s"
    },
    {
      icon: Scissors,
      title: "Smart Auto-Crop",
      description: "AI-driven vertical reframing using MediaPipe face detection and YOLOv8 subject tracking for stabilized 9:16 shots.",
      delay: "0.2s"
    },
    {
      icon: Subtitles,
      title: "Dynamic Subtitles",
      description: "Powered by faster-whisper with word-level precision. Auto-generate and burn styled captions directly into clips.",
      delay: "0.3s"
    },
    {
      icon: Type,
      title: "Viral Hook Titles",
      description: "Add high-impact text overlays with customized fonts to capture attention in the first 3 seconds.",
      delay: "0.4s"
    },
    {
      icon: Zap,
      title: "GPU Accelerated",
      description: "Auto-detects NVIDIA hardware for 10x faster processing. Seamlessly falls back to optimized CPU mode.",
      delay: "0.5s"
    },
    {
      icon: Shield,
      title: "Private & Local",
      description: "100% self-hosted via Docker. Your data and videos stay on your infrastructure. Full privacy by design.",
      delay: "0.6s"
    }
  ];

  const steps = [
    { title: "Input Content", description: "Paste any YouTube URL or upload a local MP4/MOV file. yt-dlp handles high-quality extraction automatically." },
    { title: "AI Generation", description: "The pipeline transcribes, detects scene boundaries, and identifies the best clips using advanced LLMs." },
    { title: "Creative Polish", description: "Apply smart vertical cropping, auto-subtitles, and hook overlays with a single click." },
    { title: "Export & Share", description: "Download your viral-ready shorts directly to your device. No watermarks, no limits." }
  ];

  const checkIcon = <div className="flex items-center justify-center w-6 h-6 rounded-full bg-success/20 text-success mx-auto"><Check size={14} strokeWidth={3} /></div>;
  const xIcon = <span className="text-zinc-600 text-xs font-mono">$$$ PAID</span>;

  const faqs = [
    {
      question: "What is ClippyMe and how does it work?",
      answer: "ClippyMe is a free, open source AI clip generator that transforms long YouTube videos or local uploads into viral-ready short clips in 9:16 vertical format. It uses a multi-step AI pipeline: faster-whisper for transcription, PySceneDetect for scene detection, and Google Gemini AI for identifying the most engaging viral moments."
    },
    {
      question: "Is ClippyMe really free? What's the catch?",
      answer: "ClippyMe is 100% free and open source. You self-host it using Docker on your own machine. It uses the Google Gemini API (required) which offers a generous free tier. There are no watermarks, no usage limits, and no monthly subscriptions."
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

  return (
    <div className="min-h-screen bg-background text-zinc-300 font-sans selection:bg-primary/20">
      {/* Mesh Background */}
      <div className="fixed inset-0 bg-gradient-mesh opacity-50 pointer-events-none -z-10" />
      <div className="fixed inset-0 bg-grid pointer-events-none -z-10 opacity-30" />

      {/* Navigation */}
      <nav className="fixed top-0 w-full z-50 bg-background/60 backdrop-blur-xl border-b border-white/5">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3 group cursor-pointer" onClick={() => window.scrollTo({top: 0, behavior: 'smooth'})}>
            <div className="w-10 h-10 rounded-xl bg-primary flex items-center justify-center shadow-glow-primary group-hover:scale-110 transition-transform duration-500">
              <img src="/logo-clippyme.png" alt="ClippyMe" className="w-7 h-7" />
            </div>
            <span className="text-xl font-black text-white tracking-tighter">CLIPPYME</span>
          </div>
          
          <div className="hidden lg:flex items-center gap-10 text-sm font-bold uppercase tracking-widest text-zinc-500">
            <a href="#features" className="hover:text-primary transition-colors">Features</a>
            <a href="#how-it-works" className="hover:text-primary transition-colors">Process</a>
            <a href="#comparison" className="hover:text-primary transition-colors">Pricing</a>
            <a href="#faq" className="hover:text-primary transition-colors">FAQ</a>
          </div>

          <div className="flex items-center gap-4">
            <a
              href="https://github.com/fralapo/clippyme"
              target="_blank"
              rel="noopener noreferrer"
              className="hidden sm:flex items-center gap-2 p-2.5 rounded-xl bg-white/5 border border-white/10 hover:bg-white/10 transition-all"
              title="View on GitHub"
            >
              <Github size={20} className="text-white" />
            </a>
            <button
              onClick={onLaunchApp}
              className="btn-primary-glow px-6 py-2.5 rounded-xl text-sm"
            >
              Launch App
            </button>
          </div>
        </div>
      </nav>

      {/* Hero Section */}
      <section className="relative pt-48 pb-32 px-6 overflow-hidden">
        <div className="max-w-7xl mx-auto flex flex-col items-center">
          <div className="inline-flex items-center gap-3 bg-white/5 border border-white/10 rounded-full px-5 py-2 text-xs font-bold text-zinc-400 mb-10 animate-fade-in uppercase tracking-[0.2em]">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-primary"></span>
            </span>
            Open Source AI Video Engine
          </div>

          <div className="relative mb-12 text-center animate-fade-in" style={{ animationDelay: '0.1s' }}>
            <h1 className="text-5xl md:text-8xl lg:text-9xl font-black leading-[0.9] text-white mb-8 tracking-tighter">
              CLIPS FOR <br/>
              <span className="brand-gradient-text italic">THE VIRAL ERA</span>
            </h1>
            
            <p className="text-lg md:text-2xl text-zinc-400 max-w-3xl mx-auto leading-relaxed font-medium">
              Transform long YouTube videos into high-engagement vertical shorts. 
              Self-hosted, GPU-accelerated, and 100% free.
            </p>
          </div>

          <div className="flex flex-col sm:flex-row items-center gap-6 mb-20 animate-fade-in" style={{ animationDelay: '0.2s' }}>
            <button
              onClick={onLaunchApp}
              className="flex items-center gap-3 bg-primary hover:bg-primary-dark text-white px-10 py-5 rounded-2xl font-black shadow-2xl shadow-primary/30 transition-all active:scale-[0.95] text-xl tracking-tight"
            >
              GET STARTED
              <ArrowRight size={24} />
            </button>
            <a
              href="https://github.com/fralapo/clippyme"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-3 bg-white/5 border border-white/10 text-white px-10 py-5 rounded-2xl font-black transition-all hover:bg-white/10 text-xl tracking-tight"
            >
              <Github size={24} />
              SOURCE CODE
            </a>
          </div>

          {/* Social Proof / Trust Bar */}
          <div className="w-full max-w-4xl grid grid-cols-2 md:grid-cols-4 gap-8 py-12 border-y border-white/5 animate-fade-in" style={{ animationDelay: '0.3s' }}>
            <div className="flex flex-col items-center gap-1">
                <span className="text-3xl font-black text-white">100%</span>
                <span className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest">Self-Hosted</span>
            </div>
            <div className="flex flex-col items-center gap-1">
                <span className="text-3xl font-black text-white">CUDA</span>
                <span className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest">Accelerated</span>
            </div>
            <div className="flex flex-col items-center gap-1">
                <span className="text-3xl font-black text-white">Gemini</span>
                <span className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest">AI Core</span>
            </div>
            <div className="flex flex-col items-center gap-1">
                <span className="text-3xl font-black text-white">$0</span>
                <span className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest">Lifetime Cost</span>
            </div>
          </div>
        </div>
      </section>

      {/* Features Section */}
      <section id="features" className="py-32 px-6 bg-surface-darker/30">
        <div className="max-w-7xl mx-auto">
          <div className="flex flex-col lg:flex-row lg:items-end justify-between mb-20 gap-8">
            <div className="max-w-2xl">
                <h2 className="text-4xl md:text-6xl font-black text-white mb-6 tracking-tighter uppercase">Power tools <br/>for creators.</h2>
                <p className="text-xl text-zinc-500 leading-relaxed font-medium">Everything you need to dominate social media with high-quality automated content.</p>
            </div>
            <div className="flex gap-4">
                <div className="p-4 rounded-2xl bg-white/5 border border-white/10 flex items-center gap-3">
                    <TikTokIcon size={24} className="text-white" />
                    <Instagram size={24} className="text-pink-500" />
                    <Youtube size={24} className="text-red-500" />
                </div>
            </div>
          </div>
          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
            {features.map((feature, i) => (
              <FeatureCard key={i} {...feature} />
            ))}
          </div>
        </div>
      </section>

      {/* Process Section */}
      <section id="how-it-works" className="py-32 px-6">
        <div className="max-w-7xl mx-auto grid lg:grid-cols-2 gap-20">
          <div>
            <div className="sticky top-32">
                <h2 className="text-4xl md:text-6xl font-black text-white mb-8 tracking-tighter uppercase">Simple steps to <br/>go viral.</h2>
                <p className="text-xl text-zinc-500 mb-12 max-w-md">Our AI handles the heavy lifting, you handle the creativity.</p>
                
                <div className="p-8 glass-panel border-primary/20 relative overflow-hidden group">
                    <div className="absolute -right-10 -bottom-10 w-40 h-40 bg-primary/10 rounded-full blur-3xl group-hover:bg-primary/20 transition-all duration-700" />
                    <div className="flex items-center gap-4 mb-6">
                        <div className="w-3 h-3 rounded-full bg-red-500" />
                        <div className="w-3 h-3 rounded-full bg-yellow-500" />
                        <div className="w-3 h-3 rounded-full bg-green-500" />
                    </div>
                    <div className="font-mono text-sm text-primary/80 space-y-2">
                        <p>&gt; BOOTING_PIPELINE...</p>
                        <p>&gt; DETECTING_FACE_TARGETS...</p>
                        <p>&gt; CALCULATING_ENGAGEMENT_SCORE...</p>
                        <p>&gt; STATUS: OPTIMIZING_9:16_OUTPUT</p>
                    </div>
                </div>
            </div>
          </div>
          <div className="space-y-16 pt-8">
            {steps.map((step, i) => (
              <StepCard key={i} number={i + 1} {...step} />
            ))}
          </div>
        </div>
      </section>

      {/* Comparison Table */}
      <section id="comparison" className="py-32 px-6 bg-surface-darker/50 border-y border-white/5">
        <div className="max-w-5xl mx-auto">
          <div className="text-center mb-20">
            <h2 className="text-4xl md:text-6xl font-black text-white mb-6 tracking-tighter uppercase">Zero cost. Zero limits.</h2>
            <p className="text-xl text-zinc-500 max-w-2xl mx-auto">Why pay hundreds per month when you can own the tool?</p>
          </div>
          <div className="glass-panel border-white/5 overflow-hidden">
            <div className="overflow-x-auto">
                <table className="w-full text-left">
                <thead>
                    <tr className="border-b border-white/10 bg-white/5">
                    <th className="py-6 px-8 text-xs font-black uppercase tracking-[0.2em] text-zinc-500">Capability</th>
                    <th className="py-6 px-8 text-center text-xs font-black uppercase tracking-[0.2em] text-primary">ClippyMe</th>
                    <th className="py-6 px-8 text-center text-xs font-black uppercase tracking-[0.2em] text-zinc-500">SaaS Competitors</th>
                    <th className="py-6 px-8 text-center text-xs font-black uppercase tracking-[0.2em] text-zinc-500">Basic Editors</th>
                    </tr>
                </thead>
                <tbody>
                    <ComparisonRow feature="Monthly Cost" clippyme={<span className="text-success">$0 / FREE</span>} opusclip={xIcon} kapwing={xIcon} />
                    <ComparisonRow feature="Privacy (Self-Hosted)" clippyme={checkIcon} opusclip={<span className="text-zinc-600">❌</span>} kapwing={<span className="text-zinc-600">❌</span>} />
                    <ComparisonRow feature="AI Viral Analysis" clippyme={checkIcon} opusclip={checkIcon} kapwing={<span className="text-zinc-600">❌</span>} />
                    <ComparisonRow feature="Smart Reframing" clippyme={checkIcon} opusclip={checkIcon} kapwing={<span className="text-zinc-600">❌</span>} />
                    <ComparisonRow feature="Unlimited Export" clippyme={checkIcon} opusclip={<span className="text-zinc-600">❌</span>} kapwing={<span className="text-zinc-600">❌</span>} />
                    <ComparisonRow feature="GPU Support" clippyme={checkIcon} opusclip={<span className="text-zinc-600">CLOUD</span>} kapwing={<span className="text-zinc-600">❌</span>} />
                </tbody>
                </table>
            </div>
          </div>
        </div>
      </section>

      {/* FAQ Section */}
      <section id="faq" className="py-32 px-6">
        <div className="max-w-4xl mx-auto">
          <div className="text-center mb-20">
            <h2 className="text-4xl md:text-6xl font-black text-white mb-6 tracking-tighter uppercase">Knowledge Base</h2>
            <p className="text-xl text-zinc-500">Everything you need to know about the engine.</p>
          </div>
          <div className="space-y-4">
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

      {/* Final CTA */}
      <section className="py-48 px-6 relative overflow-hidden">
        <div className="absolute inset-0 bg-primary/5 -z-10" />
        <div className="max-w-5xl mx-auto text-center relative">
          <h2 className="text-5xl md:text-8xl font-black text-white mb-10 tracking-tighter uppercase italic">Ready to go viral?</h2>
          <p className="text-2xl text-zinc-400 mb-12 max-w-2xl mx-auto font-medium">Join the next generation of creators. Download, deploy, and dominate.</p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-6">
            <button
              onClick={onLaunchApp}
              className="btn-primary-glow px-12 py-6 rounded-2xl text-2xl font-black"
            >
              LAUNCH NOW
            </button>
            <a
              href="https://github.com/fralapo/clippyme"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-3 text-zinc-500 hover:text-white transition-all text-sm font-bold uppercase tracking-widest"
            >
              <Github size={20} />
              Star Repository
            </a>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-white/5 py-20 px-6 bg-background">
        <div className="max-w-7xl mx-auto flex flex-col md:flex-row items-center justify-between gap-12">
          <div className="flex flex-col items-center md:items-start gap-4">
            <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-lg bg-zinc-800 flex items-center justify-center border border-white/5">
                    <img src="/logo-clippyme.png" alt="ClippyMe" className="w-5 h-5 opacity-50" />
                </div>
                <span className="text-lg font-black text-white tracking-tighter uppercase opacity-50">CLIPPYME</span>
            </div>
            <p className="text-xs text-zinc-600 font-medium">© 2026 ClippyMe. All rights reserved. <br/> Built for performance and privacy.</p>
          </div>
          
          <div className="flex gap-16">
            <div className="flex flex-col gap-4">
                <span className="text-[10px] font-black text-zinc-700 uppercase tracking-[0.2em]">Social</span>
                <a href="https://github.com/fralapo/clippyme" target="_blank" rel="noreferrer" className="text-sm font-bold text-zinc-500 hover:text-primary transition-colors">GitHub</a>
                <a href="#" className="text-sm font-bold text-zinc-500 hover:text-primary transition-colors">Twitter</a>
            </div>
            <div className="flex flex-col gap-4">
                <span className="text-[10px] font-black text-zinc-700 uppercase tracking-[0.2em]">Product</span>
                <a href="#features" className="text-sm font-bold text-zinc-500 hover:text-primary transition-colors">Features</a>
                <a href="#faq" className="text-sm font-bold text-zinc-500 hover:text-primary transition-colors">FAQ</a>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}

const ChevronDown = ({ size, className }) => (
    <svg 
        width={size} height={size} viewBox="0 0 24 24" fill="none" 
        stroke="currentColor" strokeWidth="2" strokeLinecap="round" 
        strokeLinejoin="round" className={className}
    >
        <path d="m6 9 6 6 6-6"/>
    </svg>
);
