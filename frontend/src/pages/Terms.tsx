import { Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { APP_NAME, CONTACT_EMAIL } from "@/lib/brand";

export function TermsPage() {
  return (
    <div className="min-h-screen bg-gray-950 text-white">
      <div className="max-w-2xl mx-auto px-6 py-16">
        <Link
          to="/"
          className="inline-flex items-center gap-2 text-sm text-gray-400 hover:text-white transition-colors mb-10"
        >
          <ArrowLeft size={16} />
          {APP_NAME}
        </Link>

        <div className="prose prose-invert prose-sm max-w-none">
          <h1 className="text-2xl font-bold text-white mb-1">Terms of Service</h1>
          <p className="text-gray-500 text-sm mb-8">Last updated: 2026-05-30</p>

          <Section title="1. Acceptance">
            <p>
              By using {APP_NAME}, you agree to these Terms of Service. If you do not agree, do
              not use the service.
            </p>
          </Section>

          <Section title="2. Service Description">
            <p>
              {APP_NAME} is a self-hosted content management and publishing pipeline. It automates
              the organization, captioning, and cross-platform publishing of media
              (photos and videos) to Instagram, YouTube Shorts, and TikTok. It is an operator-only
              tool and is not offered as a commercial SaaS product.
            </p>
          </Section>

          <Section title="3. Permitted Use">
            <ul>
              <li>
                You may not use this tool to automate publishing on accounts you do not own or have
                explicit authorization to manage.
              </li>
              <li>You may not use this tool in violation of any applicable law.</li>
            </ul>
          </Section>

          <Section title="4. Intellectual Property">
            <p>
              All content (photos, videos) remains the property of the operator.
              AI-generated captions produced by this tool are considered the operator's output. The
              underlying software is open source under the MIT License.
            </p>
          </Section>

          <Section title="5. Third-Party Platform Compliance">
            <p>Use of this tool is subject to the terms of service of each connected platform:</p>
            <ul>
              <li>
                <a
                  href="https://www.facebook.com/terms.php"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-amber-400 hover:text-amber-300"
                >
                  Meta / Instagram Terms
                </a>
              </li>
              <li>
                <a
                  href="https://www.tiktok.com/legal/page/global/terms-of-service/en"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-amber-400 hover:text-amber-300"
                >
                  TikTok Terms of Service
                </a>
              </li>
              <li>
                <a
                  href="https://www.youtube.com/t/terms"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-amber-400 hover:text-amber-300"
                >
                  YouTube Terms of Service
                </a>
              </li>
            </ul>
            <p>
              It is the operator's responsibility to ensure all published content complies with the
              rules of each platform.
            </p>
          </Section>

          <Section title="6. Disclaimer of Warranties">
            <p>
              This service is provided "as is" without warranty of any kind. No guarantee is made
              regarding uptime, publishing success rates, or continued API compatibility.
              Third-party platforms may change or revoke API access at any time.
            </p>
          </Section>

          <Section title="7. Limitation of Liability">
            <p>The operator is not liable for:</p>
            <ul>
              <li>Account suspensions or bans imposed by Instagram, TikTok, or YouTube.</li>
              <li>Missed or failed posts due to API outages or rate limiting.</li>
              <li>Data loss due to third-party infrastructure failures.</li>
            </ul>
          </Section>

          <Section title="8. Termination">
            <p>
              The operator may discontinue use of this tool at any time by shutting down the
              self-hosted service and revoking all connected OAuth tokens.
            </p>
          </Section>

          <Section title="9. Changes to These Terms">
            <p>
              These terms may be updated at any time. The "Last updated" date at the top reflects
              the most recent revision.
            </p>
          </Section>

          <Section title="10. Contact">
            <p>
              Questions:{" "}
              <a href={`mailto:${CONTACT_EMAIL}`} className="text-amber-400 hover:text-amber-300">
                {CONTACT_EMAIL}
              </a>
            </p>
          </Section>
        </div>

        <div className="mt-12 pt-8 border-t border-white/10 flex items-center justify-between text-sm text-gray-500">
          <Link to="/" className="hover:text-gray-300 transition-colors">← {APP_NAME}</Link>
          <Link to="/privacy-policy" className="hover:text-gray-300 transition-colors">Privacy Policy →</Link>
        </div>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mb-8">
      <h2 className="text-base font-semibold text-white mb-3 pb-2 border-b border-white/10">{title}</h2>
      <div className="space-y-3 text-gray-300 text-sm leading-relaxed">{children}</div>
    </div>
  );
}
