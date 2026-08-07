import { redirect } from 'next/navigation';

export default function PostsPageRedirect() {
  redirect('/publish?tab=manage');
}
