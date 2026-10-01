import type { Post } from "@/types/post";

export function HashtagPanel({ post }: { post: Post }) {
  if (!(post.hashtags_en?.length || post.hashtags_ar?.length)) return null;
  return (
    <div className="p-4 border-b border-gray-800 space-y-2">
      <label className="text-xs font-semibold uppercase tracking-widest text-gray-500">Hashtags</label>
      <div className="flex flex-wrap gap-1">
        {post.hashtags_en?.map((t) => (
          <span key={t} className="text-xs bg-gray-800 text-blue-300 px-2 py-0.5 rounded">#{t}</span>
        ))}
      </div>
      <div className="flex flex-wrap gap-1">
        {post.hashtags_ar?.map((t) => (
          <span key={t} className="text-xs bg-gray-800 text-purple-300 px-2 py-0.5 rounded" dir="rtl">#{t}</span>
        ))}
      </div>
    </div>
  );
}
