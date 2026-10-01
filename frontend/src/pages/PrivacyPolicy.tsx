import { Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { APP_NAME, CONTACT_EMAIL, OPERATOR_NAME } from "@/lib/brand";

export function PrivacyPolicyPage() {
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
          <h1 className="text-2xl font-bold text-white mb-1">Privacy Policy</h1>
          <p className="text-gray-500 text-sm mb-8">Last updated: 2026-05-30</p>

          <Section title="1. Who We Are">
            <p>
              {APP_NAME} is a self-hosted content automation tool operated solely by{" "}
              {OPERATOR_NAME}. It is not a consumer-facing product — no third parties create accounts
              or submit personal data.
            </p>
            <p>
              <strong>Operator:</strong> {OPERATOR_NAME}, operating as {APP_NAME}
              <br />
              <strong>Contact:</strong>{" "}
              <a href={`mailto:${CONTACT_EMAIL}`} className="text-amber-400 hover:text-amber-300">
                {CONTACT_EMAIL}
              </a>
            </p>
          </Section>

          <Section title="2. Data We Collect">
            <p>This tool collects and processes only the following data:</p>
            <Table
              headers={["Data", "Source", "Purpose"]}
              rows={[
                [
                  "Instagram media archive",
                  "Operator's own Instagram account",
                  "Download + organize photos/videos for publishing",
                ],
                [
                  "Telegram chat ID",
                  "Operator's own Telegram account",
                  "Deliver bot notifications to the operator only",
                ],
                [
                  "YouTube OAuth refresh token",
                  "Operator's own Google account",
                  "Publish Shorts to operator's YouTube channel",
                ],
                [
                  "TikTok access token",
                  "Operator's own TikTok account",
                  "Publish videos to operator's TikTok account",
                ],
              ]}
            />
            <p className="font-semibold text-white">
              No data from any third-party users is collected, stored, or processed.
            </p>
          </Section>

          <Section title="3. How We Use Data">
            <p>
              All collected data is used exclusively to automate cross-platform publishing of the
              operator's own content across Instagram, YouTube Shorts, and TikTok.
            </p>
            <ul>
              <li>Media files are processed (resized, captioned) and published to the operator's own social media accounts.</li>
              <li>OAuth tokens are used solely to authenticate API calls on behalf of the operator.</li>
              <li>Telegram chat ID is used solely to send publishing notifications to the operator.</li>
            </ul>
          </Section>

          <Section title="4. Data Storage">
            <Table
              headers={["Provider", "Data stored", "Location"]}
              rows={[
                ["Supabase (PostgreSQL)", "Media metadata, post records, captions", "EU region"],
                ["Self-hosted server (VPS)", "Video files, pipeline logs", "Operator-chosen region"],
                ["Cloudflare R2", "Published video files (public CDN)", "Global CDN"],
              ]}
            />
            <p>All data is encrypted in transit (TLS 1.2+) and at rest.</p>
          </Section>

          <Section title="5. Third-Party Services">
            <p>
              This tool integrates with the following platforms using only the operator's own
              credentials:
            </p>
            <ul>
              <li><strong>Instagram Graph API</strong> (Meta) — download operator's own media</li>
              <li><strong>TikTok Content Posting API</strong> — publish videos to operator's TikTok account</li>
              <li><strong>YouTube Data API v3</strong> (Google) — publish Shorts to operator's YouTube channel</li>
              <li><strong>Supabase</strong> — database hosting</li>
              <li><strong>Telegram Bot API</strong> — operator notifications</li>
              <li><strong>Cloudflare R2</strong> — media storage and delivery</li>
            </ul>
            <p>
              Each service's own privacy policy governs how they handle data on their
              infrastructure.
            </p>
          </Section>

          <Section title="6. Data Retention">
            <ul>
              <li>OAuth tokens are stored until manually revoked by the operator.</li>
              <li>Media files are stored until manually deleted via the operator's dashboard.</li>
              <li>Logs are rotated and deleted after 30 days.</li>
            </ul>
          </Section>

          <Section title="7. Your Rights">
            <p>
              As this tool has no end users other than the operator, all data deletion and
              modification can be performed directly via the self-hosted dashboard or by deleting
              the database.
            </p>
          </Section>

          <Section title="8. Changes to This Policy">
            <p>
              The operator may update this policy at any time. The "Last updated" date at the top
              of this document reflects the most recent revision.
            </p>
          </Section>

          <Section title="9. Contact">
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
          <Link to="/terms" className="hover:text-gray-300 transition-colors">Terms of Service →</Link>
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

function Table({ headers, rows }: { headers: string[]; rows: string[][] }) {
  return (
    <div className="overflow-x-auto my-4">
      <table className="w-full text-sm border border-white/10 rounded-lg overflow-hidden">
        <thead>
          <tr className="bg-white/5">
            {headers.map((h) => (
              <th key={h} className="text-left px-4 py-2.5 text-gray-300 font-medium border-b border-white/10">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-b border-white/5 last:border-0">
              {row.map((cell, j) => (
                <td key={j} className="px-4 py-2.5 text-gray-400">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
