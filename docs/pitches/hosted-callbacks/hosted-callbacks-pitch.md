# Hosted mode: set up callbacks at startup

## Problem

In hosted mode, many people share one tater server, each working on their own project in their own session. Every click in the annotation page is handled by a callback on the server, and the web framework only lets each callback be set up once for the whole server. Tater does that setup the first time it needs it: while building the first session after the server starts. Every later session reuses what the first one set up.

Most of that setup is generic. When a request arrives, the callback looks up whose session it came from and works on that user's project. That's how two people on different schemas can annotate side by side without seeing each other's data, which [#115](https://github.com/text-harvest/tater/issues/115) checked under load. But a few pieces are shaped by whatever project the first user happened to bring:

- **The instructions button.** Whether it opens anything depends on whether the first project had instructions. If the first session after a restart uses a schema without instructions, the button does nothing for every later project until the server restarts again. The built-in examples all have instructions, so this only shows when someone uploads their own schema first.
- **Clearing hidden fields inside repeaters.** A field can be shown only when another field has a certain value, and when it's hidden its value should be cleared, so stale answers don't end up in the annotations. Showing and hiding works for everyone. Clearing is set up field by field, for the conditional fields in the first project's repeaters only. In a later project with a conditional field inside a repeater, hiding the field leaves its old value in place, and that value goes into the user's download. If two projects use the same field names, the first project's rules may even clear the wrong field in the other. That last part hasn't been tested.
- **The first session never goes away.** The callbacks set up from the first session keep hold of it, so even after it's been dropped from the server, its whole project stays in memory until the next restart. For a 10,000-document project that's roughly 50 to 100 MB. It's a fixed cost, not a growing leak, but it's memory a deployment has to plan for, for a session nobody is using.

#115 fixed the dangerous version of this: a request from a session that had ended used to fall back to the first session, showing one user another user's documents. Such requests now do nothing. What's left are these quieter differences, which depend on who arrived first after a restart. That's hard to predict, and hard to reproduce when someone reports it.

## Appetite

Two to three days. The instructions button and the setup move are small; clearing hidden fields is where the time goes.

## Solution

Set up every callback when the server starts, before anyone arrives, from no project at all. Every session, the first included, then gets exactly the same treatment.

```
 today                                     proposed

 server starts                             server starts
   (nothing set up)                          set up all callbacks, generic
 first user uploads project A                  (no project needed)
   build A's session                       any user uploads a project
   set up callbacks, partly from A ──┐       build their session
 later users                          │      (nothing else to set up)
   build their sessions               │
   reuse A's setup  ◄─────────────────┘    every request finds its own session;
   A stays in memory for good              ended sessions can be freed
```

This is safe for the upload page: once the first session has started today, every callback is already set up, and the upload page works fine alongside them. Setting them up at startup is the same situation, reached earlier.

Three changes get there:

1. **Setup no longer needs a project.** The generic callbacks already only need the server and a way to find the caller's session. They'd be set up once at startup, and building a session would no longer set anything up. Single-user mode, which has exactly one project for its whole life, can keep working as it does now.
2. **The instructions button always works.** Set up its callback regardless of project. On a page without the button, it simply never fires.
3. **Clearing hidden fields becomes generic.** Showing and hiding already works this way: one callback for every conditional field in every project, reading each field's rule from a small piece of data on the page. Clearing would work the same way, from the same rule data, instead of one callback per field from the first project.

A side benefit: today the setup has to happen while the first user submits the upload form, so that the callbacks exist by the time their browser opens the annotation page, and there's a workaround to make that timing work. Setting up at startup removes the need for it.

## Details and open questions

- **Will generic clearing cost requests?** A generic callback listens to every control on the page, so it would run on every edit, and the performance rules from [#108](https://github.com/text-harvest/tater/issues/108) warn against exactly that. Show/hide already listens to the same controls, though, so clearing may be able to ride on the same trigger, or even be part of the same callback, at no extra cost. It needs to stop immediately when no conditional field is affected, and the existing large-project checks of requests and bytes per action should show no change.
- **Does the field-name clash happen?** The first thing to check, with two projects that share a field name but have different conditions. If it does, it's another reason to do this soon; if not, the issue is "only" stale values in later projects.
- **Should single-user mode move too?** It doesn't have the problem, since its one project is the first. Moving it would mean one setup path for both modes, which is easier to test. Keeping it means less change. Prefer one path if it falls out naturally, without forcing it.
- **Clearing outside repeaters.** Conditional fields that aren't inside a repeater are shown and hidden, but never cleared, in either mode. That looks deliberate, but it's worth confirming while the clearing code is open. Changing it is out of scope unless it's trivially the same mechanism.
- **How we'll know it's done.** A hosted test where the second session's project differs from the first: the first has no instructions and the second does, and the second has a conditional field inside a repeater. The second must behave exactly as it would if it had been first. A second check: once a session is dropped, it's actually freed from memory.

## Rabbit holes

- **Reworking how conditional fields work in general.** Only replace how clearing is set up; keep the rules and the show/hide behaviour as they are.
- **Hunting other first-session effects by guesswork.** The setup code has been read through for this; these three are what's there. Once everything is set up at startup there's no first session left to depend on, so the tests above are enough.
- **Shrinking memory per session.** Sessions cost 33–53 MB each at 10,000 documents. Making them smaller is a separate optimisation, only worth doing if many large projects need to share a small server.

## No-gos

- Custom callbacks per project. Hosted mode only accepts schema files today, not Python config files with their own callbacks. Uploading Python configs is [#56](https://github.com/text-harvest/tater/issues/56); if that happens, per-project callbacks will need their own design, since they can't all be set up at startup.
- Sessions that survive a restart, several server processes, and user accounts. See [#115](https://github.com/text-harvest/tater/issues/115) for the deployment limits and [#119](https://github.com/text-harvest/tater/issues/119) for user management.
