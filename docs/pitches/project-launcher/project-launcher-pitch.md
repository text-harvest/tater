# A launcher for projects with several annotators

## Problem

A real annotation project is almost always one project with several annotators: one schema, one set of documents, a handful of people each labelling their share, often with some overlap so agreement can be checked. Someone sets it up and collects the results. We're assuming that person, the admin, always exists, and that it won't always be one of us.

Tater has two modes, and neither is this.

- **Single mode** is one project and one annotator. It's the solid one: work is saved to a file as the annotator goes, a restart picks up where they left off, and Python configs with custom rules work. But it has no idea that a second person exists. Two people on one instance share everything and overwrite each other.
- **Hosted mode** is many unrelated projects and anyone who turns up. It's built for trying tater out: upload a schema and documents, annotate, download. Work lives in the browser and in the server's memory, so a restart or a busy server loses whatever wasn't downloaded. [#115](https://github.com/text-harvest/tater/issues/115) measured it and made it safe, but those limits come from what it is. We now think of hosted mode as the demo, and the way in for occasional users, not as the way to run a project. That's also why we're not pursuing accounts and server-side storage for it ([#119](https://github.com/text-harvest/tater/issues/119)).

So today an admin running a real project assembles it by hand: start one single-mode instance per annotator, each on its own port with its own annotations file; give each person the right address; put some kind of login in front, because tater has none; restart whatever crashes; gather the files at the end. Every step is manual, and the mistakes are silent. Send two people the same address and they quietly overwrite each other. Send someone the wrong one and they annotate into another person's file. For an admin outside our group, working only from what we've written down, that's too much to get right.

## Appetite

Two weeks. The first week is the core: starting the processes, one front door, and knowing who is who. The second is what makes it pleasant to run: stopping idle processes, the admin's view, and the documentation. If time runs short, the second week's pieces are cut in that order, last first.

## Solution

A launcher. The admin describes the project once, in a small project file: the schema or config, the documents, where results go, and who the annotators are. One command starts it. Behind one address, the launcher runs an ordinary single-mode tater for each annotator and sends each person to their own.

```
                         project file
                  (schema, documents, annotators,
                         results folder)
                               │
                               ▼
  alice ──┐              ┌───────────┐        ┌─ tater for alice ──► results/alice
  bob   ──┼─ one address ►  launcher  ├────────┼─ tater for bob   ──► results/bob
  carol ──┘              │           │        └─ tater for carol ──► results/carol
                         │ who is it? │
  admin ─── status page ─►  start, watch,       each one is today's single mode:
                         │  restart, stop        saves as you go, resumes after
                         └───────────┘          a restart
```

### One tater per annotator

Each annotator gets their own single-mode process, with their own annotations file and, if the admin wants, their own share of the documents. Nothing about tater itself changes: each process is exactly what runs today when one person annotates on their own machine.

The launcher starts them, watches them, and restarts one if it crashes. Because single mode saves as it goes, a restart costs the annotator nothing but a page reload.

### One front door

Annotators all use the same address. The launcher works out who each request is from and passes it to that person's process. The admin exposes one address, by whatever means suits the data (see below), instead of one per annotator. Tater's pages talk to the server with ordinary web requests and nothing more exotic, so passing them along is simple.

### Knowing who is who

Two ways, chosen in the project file:

- **Personal links.** The launcher prints one secret link per annotator for the admin to send out. Opening it once marks that browser as that annotator. This is how Jupyter notebooks have long worked, and it needs nothing else installed. It's as safe as the link is secret, so it suits data that isn't sensitive, or a server that's already only reachable by the right people.
- **A login in front.** Where a login service already sits in front of the server, such as a campus sign-on, a cloud platform's built-in sign-in, or a tunnel provider's access control, it tells the launcher each visitor's email, and the launcher matches that against the annotator list. Tater then handles no logins at all. This is the one to use for sensitive data.

Either way, a visitor who isn't on the list gets a plain "not part of this project" page, never someone else's work.

### Stopping idle processes

An annotator who has stopped for the day doesn't need a running process. An open tater page sends nothing while its user is idle, so the launcher can see who has gone quiet, stop their process, and start it again on their next visit. Since the work is on disk, this is harmless, unlike hosted mode, where dropping a session loses it. Memory then follows the number of people working, not the number enrolled.

### The admin's view

A status page for the admin only: who is working, how far each annotator has got, and where the result files are. The same information is available from the command line.

### Why not one shared server?

The other way to build this is a single tater process that holds every annotator, as [#82](https://github.com/text-harvest/tater/issues/82) first sketched. We compared them.

| | One shared process | One process per annotator (this pitch) |
|---|---|---|
| Keeping annotators apart | Every action must pick the right person's data; one missed spot writes into someone else's file | Guaranteed: a process never opens another annotator's file |
| Changes inside tater | The saving code becomes per-annotator | None |
| Python configs, custom rules | Need rechecking per annotator | Work as today |
| Memory | Lowest: documents loaded once | About 120 MB per annotator on a small project, up to 200 MB at 10,000 documents; less with idle ones stopped |
| Many people acting at once | Everyone shares one process; in #115's load test twenty simultaneous Nexts took ten times as long as one alone | No one slows anyone else down |
| A crash | Stops everyone | Stops one person, briefly |
| Different documents per annotator | Needs building | Comes free |
| Things that span annotators live, such as a shared queue of documents | Easy | Hard: the processes only share files |

The shared process wins on memory and on live features across annotators. Separate processes win on the thing that matters most, which is that nobody's work can end up in the wrong place, and they do it without touching the code that saves annotations. Hosted mode showed how easy that kind of mistake is: until #115, a user whose session had ended could see another user's documents.

The admin's side, a project file and one address, would be the same either way. If memory ever becomes the constraint, the shared process can replace what's behind the front door without anyone changing how they run a project.

### Where it runs, and for what data

The launcher is the same everywhere. What changes is what sits in front of it, and that depends on the data.

| Where | In front of it | Data it suits |
|---|---|---|
| The admin's own machine | A temporary tunnel, personal links | Public or synthetic data, short runs |
| A lab server or virtual machine | The institution's VPN; or a web proxy with encryption and a login; or a tunnel with access control | Internal data; sensitive data when the server and the login are approved for it |
| A container platform | The platform's own sign-in; a mounted disk for the results | Whatever the platform is approved for |

The documentation would say this plainly, with the requirements first (encryption in transit, a login for anything sensitive, results on a disk that survives restarts) and specific tools only as examples. For sensitive data the starting point is an approved server behind the institution's VPN or sign-on, not a tunnel through a third party that can read the traffic.

## Details and open questions

- **A shared server has a back door.** Each annotator's process listens on a private address on the server. On a machine where other people can log in, they could connect to those directly and skip the front door. Either the launcher runs on a machine only admins can log into, or the launcher and its processes share a secret that outsiders don't have, which is a small addition to tater. Decide which before calling shared servers supported.
- **Trusting the login in front.** When a login service tells the launcher who a visitor is, the launcher has to be reachable only through that service. Otherwise anyone can claim to be anyone. The documentation has to be blunt about this, and the launcher should refuse to start in this mode while listening on a public address.
- **Lost or leaked personal links.** The admin needs to be able to cancel one annotator's link and issue a new one without disturbing the others.
- **Memory.** Twenty annotators all working at once on a 10,000-document project would take about 4 GB; five take about 1 GB. Fine on a lab server, worth knowing on a small container. Stopping idle processes is what keeps this in check, so if it's cut for time, the documentation needs the sizing numbers.
- **The wait after an idle stop.** Starting tater again takes a few seconds, more for big projects. We haven't measured it. If it's long, show a "starting" page rather than a blank one.
- **One annotator, two tabs.** Both tabs reach the same process, which is what happens in single mode today when someone opens a second tab. Nothing new, but worth a test.
- **Handing out documents.** The project file can give each annotator their own documents file. Producing those files, splitting a set across people with a chosen overlap, is [#39](https://github.com/text-harvest/tater/issues/39). The launcher works without it (everyone gets everything, or the admin splits by hand) and gets better with it.
- **Icons from elsewhere.** Our browser tests suggest tater's pages fetch their icons from an outside service. If so, a server with no internet access shows no icons, and a security review will ask about the outside request. Check it, and if true, serve the icons from tater itself. Small, but it blocks the strictest deployments.
- **Platforms that already launch things.** Some institutions have a notebook hub or a research-computing portal that signs users in and starts a program for each. Tater already runs inside notebooks, so on those platforms the launcher may not be needed at all. Worth one experiment and a paragraph in the documentation, not more.
- **What becomes of hosted mode.** It stays, described as the demo and the route for occasional users, with its limits stated up front. Its remaining rough edge, [#120](https://github.com/text-harvest/tater/issues/120), is still worth fixing, at lower priority.

## Rabbit holes

- **Writing a web server or a process manager.** The launcher passes ordinary requests along and keeps a few processes alive. Keep it to that. No load balancing, no encryption of its own (that belongs to whatever is in front), no plug-in system for logins.
- **Accounts.** No passwords, sign-up, or password reset. The annotator list is in the project file, and identity comes from a link or from a login service that already exists.
- **Addresses per annotator.** One address for everyone, sorted out by who's asking. Giving each annotator their own path or subdomain looks simpler and isn't: it drags in web-address handling inside tater and extra setup for every admin.
- **Live features across annotators.** A shared document queue or live agreement scores would need the processes to coordinate. Progress on the status page, read from the result files, is as far as this goes.

## No-gos

- User accounts and server-side projects in hosted mode ([#119](https://github.com/text-harvest/tater/issues/119)), and running hosted mode across several server processes ([#70](https://github.com/text-harvest/tater/issues/70)).
- Several projects under one launcher. One launcher, one project; run two launchers for two projects.
- Merging annotators' results and reviewing disagreements. That's the second half of [#39](https://github.com/text-harvest/tater/issues/39).
- Generating one container per annotator for container platforms. One container running the launcher is the supported shape.
- The single shared process. It stays the fallback if memory forces it.
