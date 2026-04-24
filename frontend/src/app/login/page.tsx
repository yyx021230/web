import { redirect } from 'next/navigation';

/* Login is now the home page (/) */
export default function LoginPage() {
  redirect('/');
}
