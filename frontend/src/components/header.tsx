"use client";

import { Moon, Sun, LogOut, User } from "lucide-react";
import { useTheme } from "next-themes";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { useAuthStore } from "@/stores/authStore";
import { useLogout } from "@/hooks/useAuth";

export default function Header() {
  const { resolvedTheme, setTheme } = useTheme();
  const user = useAuthStore((s) => s.user);
  const logout = useLogout();
  const router = useRouter();

  const initials = user?.email?.slice(0, 2).toUpperCase() ?? "??";

  return (
    <header className="flex h-14 items-center justify-end gap-3 border-b px-4 bg-background shrink-0">
      {/* Theme toggle */}
      <Button
        variant="ghost"
        size="icon"
        onClick={() =>
          setTheme(resolvedTheme === "dark" ? "light" : "dark")
        }
        aria-label="Toggle theme"
      >
        {resolvedTheme === "dark" ? (
          <Sun className="h-4 w-4" />
        ) : (
          <Moon className="h-4 w-4" />
        )}
      </Button>

      {/* User menu */}
      <DropdownMenu>
        {/* @base-ui Trigger renders as a native button; style it directly */}
        <DropdownMenuTrigger className="inline-flex h-8 w-8 items-center justify-center rounded-full outline-none hover:ring-2 hover:ring-ring/50">
          <Avatar className="h-8 w-8 pointer-events-none">
            <AvatarFallback className="text-xs">{initials}</AvatarFallback>
          </Avatar>
        </DropdownMenuTrigger>

        <DropdownMenuContent align="end" className="w-52">
          <DropdownMenuLabel>
            <p className="text-sm font-medium truncate">{user?.email}</p>
            <Badge variant="secondary" className="mt-1 text-xs capitalize">
              {user?.plan ?? "free"}
            </Badge>
          </DropdownMenuLabel>
          <DropdownMenuSeparator />
          <DropdownMenuItem
            onClick={() => router.push("/settings")}
            className="flex items-center gap-2 cursor-pointer"
          >
            <User className="h-4 w-4" />
            Settings
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem
            onClick={logout}
            variant="destructive"
            className="flex items-center gap-2 cursor-pointer"
          >
            <LogOut className="h-4 w-4" />
            Sign out
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </header>
  );
}
