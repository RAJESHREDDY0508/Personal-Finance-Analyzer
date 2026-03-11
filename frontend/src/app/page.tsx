import { redirect } from "next/navigation";

// Middleware handles the actual redirect; this is a fallback
export default function Home() {
  redirect("/dashboard");
}
