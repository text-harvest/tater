# Hosted mode under load

## Problem

Hosted mode lets several people annotate on one tater server, each in their own session, without installing anything. It runs as a container on a hosting platform. Today the only deployment is a demo on Azure Container Apps, where robustness doesn't matter yet. A real deployment for annotation projects could run on Azure too, set up differently, or elsewhere, such as ASHE at UNC. Each platform gives the container a fixed share of memory and CPU, and has its own rules for replicas and restarts. [#108](https://github.com/text-harvest/tater/issues/108) made large projects fast for one user and measured it: at 10,000 documents an action now settles about as fast as at 500. Nobody has measured what happens when several people use one hosted server at once.

What we know about how hosted mode holds up:

- **Everything lives in one server process.** Every session keeps its whole project, documents and annotations, in that process's memory. Before #108, a 10,000-document session took about 47 MB. We don't know the figure now. The server keeps up to 100 sessions, so the worst case could be several gigabytes. A container has a hard memory limit. Our Kubernetes setup gives it 512 MB, which at the old figure holds about ten large sessions. Past the limit, the platform restarts the container, and every session on it is lost at once.
- **Any restart loses every session.** Sessions exist only in the process's memory. A new deploy, a crash, or the platform stopping an idle app sends everyone back to the upload page. A platform that scales an idle app to zero, as the Azure demo does, stops it after a few minutes with no requests, and the page sends nothing while an annotator reads or thinks. So one person pausing for a while, or a whole group at lunch, would lose any work they haven't downloaded.
- **Sessions are dropped oldest first, not idlest first.** When the 101st session starts, the one created earliest is dropped, even if its annotator is working in it right now. Their next page load sends them back to the upload page, and any work they haven't downloaded is gone. Nothing warns them.
- **Concurrent requests have never been measured.** Each user's clicks are small requests now, but they all go to one process. We don't know how response times grow with 5 or 20 people clicking at once, or which actions suffer first.
- **The server is the development server.** Hosted mode starts the web framework's built-in server, which its authors say isn't meant for production. That may be fine at this scale, or it may be the bottleneck. We don't know.

So we can't yet answer "how many annotators can one hosted server take, on how big a project?", and the eviction behaviour would lose people's work in a real deployment.

## Appetite

About a week: build the load test, measure, and fix what's small. Anything that turns out to need a redesign, such as moving sessions out of the server process, becomes its own pitch, with the measurements as its evidence.

## Solution

### 1. A load test that fits on one machine

Simulated users, plus a few real browsers to see what a person experiences.

- **Simulated users** replay a realistic annotation session at the request level, with no browser: open a project, then Next, tick a box, type a note, add a span, and so on, with pauses between actions like a real annotator. The requests come from recording what a real browser sends during the performance harness's actions from #108. The harness already logs each request's size and timing; it would also need to keep what each request contains. Without browsers, twenty users fit easily on a laptop.
- **One or two real browsers** run the existing performance actions against the same server while it's under load. They report what a person feels: how long Next takes to settle, whether typing lags.

```
 simulated users (no browser) ──┐
   open, Next, tick, note, ...   │
   with think time between       ├──► one hosted server ──► memory, CPU,
 real browser(s) ───────────────┘          (as deployed)        errors
   timed actions, as in #108                                     │
                                                                  ▼
                                 per action: p50 / p95 time, at 1, 5, 20 users
```

### 2. Scenarios

- Concurrent users: 1, 5 and 20.
- Project size: 500 and 10,000 documents.
- Everyone on the same project, and everyone on a different one.
- A burst, with everyone clicking Next at once, as well as the steady pace with pauses.
- Filling the session limit: what happens to a user whose session is dropped, and does memory come back afterwards?
- Starting a session: uploading a 10,000-document project, which costs time and a spike of memory before anyone annotates.

For each scenario, record the time each action takes (median and 95th percentile), server memory in total and per session, CPU, and any errors. As in the performance harness, results go into a table, and one baseline is committed so later changes can be compared.

### 3. Fix what doesn't scale, within the appetite

The data decides, but some likely candidates:

- Drop the session that has been idle longest, not the oldest one, so active annotators are never dropped.
- Limit sessions by memory rather than by count, since one 10,000-document project weighs as much as many small ones.
- Tell a user whose session has gone that it's gone, instead of silently showing the upload page.
- Run hosted mode on a production-grade server, if the development server turns out to be the bottleneck.

### 4. What a hosting platform has to provide

The work ends with a short list of requirements that any platform must meet to run hosted mode well, so each deployment can be checked against it, on Azure, ASHE or anywhere else. It covers:

- Memory and CPU per instance, worked out from the measured memory per session, the expected number of sessions, and some headroom.
- One instance only, or sticky sessions that send each user back to the same instance.
- A fixed secret key, shared by every instance.
- Restarts: the app shouldn't be stopped when idle while people are working, and deploys should happen outside working hours, because both drop every session.

The Azure demo doesn't need to meet it. The list is for setting up a real deployment.

## Details and open questions

- **Why the platform settings matter.** Sessions live in one process's memory. If a platform runs two instances of the app, a user's next request can reach one that has never heard of their session. Without a shared secret key, the other instance can't even read the user's session cookie. Until sessions can live outside the process, which is bigger than this pitch, each deployment needs one instance or sticky sessions. For reference, the Azure demo scales to zero, has no session affinity, and has no secret key set. That's fine for a demo, but it's the kind of setup the requirements list should catch before a real deployment. The simplest safe setting is exactly one instance, never zero and never two.
- **Target.** 20 concurrent annotators on 10,000-document projects, with Next settling within half a second at the 95th percentile, all within one instance's memory and with headroom to spare. If the planned instance size can't hold that, the result is the size it needs. Choosing between a bigger instance and less memory per session is then a cost decision.
- **Can recorded requests be replayed?** A recorded request names a particular document and carries that moment's state, and each simulated user needs its own session cookie. Replaying may need light rewriting per user. If it turns out to be fiddly, a fallback is more real browsers with fewer simulated users, at the cost of fewer users per machine.
- **Realistic pace.** Annotators act every few seconds, not continuously. The steady scenario should use pauses like that, and the burst scenario covers the worst case.
- **Where to measure.** Locally, with the server held to the same memory and CPU as the instance it will run on, so the numbers mean the same thing. The development machine has about 8 GB, enough for that. Then confirm the final numbers once on the platform chosen for real use.

## Rabbit holes

- **A general load-testing framework.** Reuse the performance harness and its recordings. Don't build or adopt a large tool.
- **Moving sessions out of the process.** A database or shared cache for sessions is a redesign. If the measurements call for it, write it up as its own pitch.
- **Speeding up single-user actions again.** #108 covered that. Only chase slowness that appears under concurrency.
- **Exact numbers on a laptop.** Relative numbers (1 user vs 20, before vs after a fix) are what matter here.

## No-gos

- Sessions that survive a server restart, and user accounts or authentication.
- Several server processes or machines behind a load balancer.
- Finding and moving between documents in big projects. That's [#112](https://github.com/text-harvest/tater/issues/112).
- Random-action and agent testing. That's [#109](https://github.com/text-harvest/tater/issues/109).
