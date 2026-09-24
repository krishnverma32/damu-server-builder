"use client";

import {
  Activity,
  Bot,
  Command,
  Gauge,
  ImagePlus,
  MessageSquare,
  Radio,
  Shield,
  Sparkles,
  UserCheck,
  Users
} from "lucide-react";
import { motion } from "framer-motion";
import type { ReactElement } from "react";

const stats = [
  { label: "Members", value: "12.8K", tone: "cyan" },
  { label: "Open Tickets", value: "18", tone: "violet" },
  { label: "Warns Today", value: "42", tone: "amber" },
  { label: "Automations", value: "97%", tone: "emerald" }
];

const modules = [
  {
    icon: MessageSquare,
    title: "Welcome System",
    detail: "Custom embeds, member pings, uploaded banners, GIPHY rotation, thumbnail control, and short default rules."
  },
  {
    icon: UserCheck,
    title: "Auto Role Routing",
    detail: "Separate join roles for human members and bots with role hierarchy-aware assignment."
  },
  {
    icon: Users,
    title: "Mass Role Console",
    detail: "Give or remove roles across all members, only bots, or only humans from one controlled panel."
  },
  {
    icon: Command,
    title: "Command Center",
    detail: "Dedicated commands channel setup with categories for moderation, utility, tickets, roles, welcome, and AI."
  }
];

const commands = [
  "welcome_setup",
  "autorole_setup",
  "commands_channel_setup",
  "mass_role",
  "dashboard_status",
  "kick",
  "ban",
  "warn",
  "ticket_setup"
];

export default function Home(): ReactElement {
  return (
    <main className="min-h-screen overflow-hidden bg-[#050712] text-slate-100">
      <div className="fixed inset-0 pointer-events-none">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_25%_20%,rgba(35,211,255,0.22),transparent_30%),radial-gradient(circle_at_75%_5%,rgba(139,92,246,0.18),transparent_30%),linear-gradient(135deg,#050712_0%,#08111f_45%,#050712_100%)]" />
        <div className="absolute inset-0 opacity-[0.08] dashboard-grid" />
      </div>

      <section className="relative mx-auto flex min-h-screen w-full max-w-7xl flex-col px-5 py-5 sm:px-8 lg:px-10">
        <header className="flex items-center justify-between border-b border-white/10 pb-4">
          <div className="flex items-center gap-3">
            <div className="grid size-10 place-items-center rounded-lg border border-cyan-300/35 bg-cyan-300/10 shadow-[0_0_30px_rgba(34,211,238,0.18)]">
              <Shield className="size-5 text-cyan-200" />
            </div>
            <div>
              <p className="text-sm uppercase tracking-[0.28em] text-cyan-200/80">Discord Sentinel</p>
              <h1 className="text-xl font-semibold text-white">Moderation Dashboard</h1>
            </div>
          </div>
          <div className="hidden items-center gap-2 rounded-full border border-emerald-300/25 bg-emerald-300/10 px-3 py-2 text-sm text-emerald-100 sm:flex">
            <Radio className="size-4" />
            Live systems online
          </div>
        </header>

        <div className="grid flex-1 gap-5 py-6 lg:grid-cols-[1.1fr_0.9fr]">
          <motion.section
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.55 }}
            className="flex flex-col justify-between rounded-lg border border-white/10 bg-white/[0.045] p-5 shadow-2xl shadow-cyan-950/30 backdrop-blur-xl"
          >
            <div>
              <div className="mb-5 flex flex-wrap gap-2">
                {["Welcome", "Moderation", "Roles", "Utility"].map((item) => (
                  <span key={item} className="rounded-md border border-white/10 bg-white/[0.06] px-3 py-1 text-sm text-slate-200">
                    {item}
                  </span>
                ))}
              </div>
              <h2 className="max-w-3xl text-4xl font-semibold leading-tight text-white sm:text-5xl lg:text-6xl">
                Premium control surface for a safer Discord server.
              </h2>
              <p className="mt-5 max-w-2xl text-base leading-7 text-slate-300">
                Configure welcomes, auto roles, mass-role operations, command routing, and moderation visibility from a clean futuristic interface designed for busy admins.
              </p>
            </div>

            <div className="mt-8 grid gap-3 sm:grid-cols-4">
              {stats.map((stat) => (
                <div key={stat.label} className="rounded-lg border border-white/10 bg-black/20 p-4">
                  <p className="text-sm text-slate-400">{stat.label}</p>
                  <p className="mt-2 text-2xl font-semibold text-white">{stat.value}</p>
                </div>
              ))}
            </div>
          </motion.section>

          <motion.aside
            initial={{ opacity: 0, x: 18 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: 0.1, duration: 0.55 }}
            className="rounded-lg border border-white/10 bg-slate-950/70 p-5 backdrop-blur-xl"
          >
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm uppercase tracking-[0.2em] text-violet-200/80">Overview</p>
                <h2 className="mt-1 text-2xl font-semibold">Server Pulse</h2>
              </div>
              <Gauge className="size-6 text-cyan-200" />
            </div>

            <div className="mt-6 space-y-3">
              {[
                ["Moderation Response", "96%"],
                ["Auto Role Coverage", "100%"],
                ["Welcome Flow", "GIPHY + Custom"],
                ["Command Channel", "#bot-commands"]
              ].map(([label, value]) => (
                <div key={label} className="flex items-center justify-between rounded-lg border border-white/10 bg-white/[0.04] px-4 py-3">
                  <span className="text-sm text-slate-300">{label}</span>
                  <span className="font-medium text-cyan-100">{value}</span>
                </div>
              ))}
            </div>

            <div className="mt-6 rounded-lg border border-cyan-300/20 bg-cyan-300/10 p-4">
              <div className="flex items-center gap-3">
                <ImagePlus className="size-5 text-cyan-100" />
                <p className="font-medium">Welcome media engine</p>
              </div>
              <p className="mt-2 text-sm leading-6 text-slate-300">
                Uploaded server-owner images and random GIPHY welcome GIFs feed directly into embedded join messages.
              </p>
            </div>
          </motion.aside>
        </div>

        <section className="relative grid gap-5 pb-8 lg:grid-cols-[0.95fr_1.05fr]">
          <div className="rounded-lg border border-white/10 bg-white/[0.045] p-5 backdrop-blur-xl">
            <div className="flex items-center gap-3">
              <Sparkles className="size-5 text-violet-200" />
              <h2 className="text-2xl font-semibold">Modules</h2>
            </div>
            <div className="mt-5 grid gap-3 sm:grid-cols-2">
              {modules.map((module) => (
                <div key={module.title} className="rounded-lg border border-white/10 bg-black/20 p-4">
                  <module.icon className="size-5 text-cyan-200" />
                  <h3 className="mt-3 font-semibold text-white">{module.title}</h3>
                  <p className="mt-2 text-sm leading-6 text-slate-400">{module.detail}</p>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-lg border border-white/10 bg-white/[0.045] p-5 backdrop-blur-xl">
            <div className="flex items-center gap-3">
              <Bot className="size-5 text-emerald-200" />
              <h2 className="text-2xl font-semibold">Command Categories</h2>
            </div>
            <div className="mt-5 flex flex-wrap gap-2">
              {commands.map((command) => (
                <span key={command} className="rounded-md border border-white/10 bg-slate-950/70 px-3 py-2 font-mono text-sm text-slate-200">
                  /{command}
                </span>
              ))}
            </div>
            <div className="mt-6 rounded-lg border border-emerald-300/20 bg-emerald-300/10 p-4">
              <div className="flex items-center gap-3">
                <Activity className="size-5 text-emerald-200" />
                <p className="font-medium">Focused admin surface</p>
              </div>
              <p className="mt-2 text-sm leading-6 text-slate-300">
                The experience stays centered on moderation, welcome automation, command routing, server safety, and utility workflows.
              </p>
            </div>
          </div>
        </section>
      </section>
    </main>
  );
}
