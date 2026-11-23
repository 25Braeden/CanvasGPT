# CanvasGPT MVP Demo Checklist

Use this checklist to quickly verify the main CanvasGPT workflow without needing a real Canvas account.

## Setup

- [ ] Start the Django development server.
- [ ] Log in with a test student account.
- [ ] Make sure the test student has a Canvas connection saved.

## Canvas Sync

- [ ] Trigger a Canvas sync using mocked or test data.
- [ ] Confirm at least one course is imported.
- [ ] Confirm at least one assignment is imported.
- [ ] Confirm the assignment shows its title, due date, points, description, and submission link.

## Checklist

- [ ] Open an imported assignment.
- [ ] Add a checklist task.
- [ ] Confirm the task appears on the assignment page.
- [ ] Mark the task complete and incomplete to confirm the toggle works.

## Suggestion Generation, Review, and Acceptance (Offline Demo)

- [ ] Keep `AI_SUGGESTIONS_MODE=demo` and leave `GEMINI_API_KEY` blank; restart Django after environment changes.
- [ ] Run migrations, then open an assignment with a description or rubric criteria.
- [ ] Click **Generate demo suggestions**; confirm only the preview updates, without reloading the page.
- [ ] Confirm no tasks were added automatically and completed work is unchanged.
- [ ] Navigate away and return; confirm the draft persists without another generation request.
- [ ] Click **Review suggestions**, edit a description/estimate, and deselect one suggestion.
- [ ] Save the review, reload, and confirm edits/selections persist without adding tasks.
- [ ] Try accepting with nothing selected; confirm a safe validation error and no task changes.
- [ ] Select suggestions and click **Accept selected tasks**; confirm only selected tasks append, with current edits and incomplete status.
- [ ] Confirm existing tasks, completed work, and study sessions are unchanged.
- [ ] Resubmit an old acceptance form; confirm it cannot create duplicates.
- [ ] Generate a new draft and discard it; confirm the checklist is unchanged.
- [ ] In two review tabs, save in one then submit the stale one; confirm it cannot overwrite or accept newer work.
- [ ] Confirm another student cannot review, discard, or accept this student's drafts.
- [ ] Confirm no real Gemini request was made; audit rows identify `demo-task-suggestions` and contain metadata only.
- [ ] Check narrow/mobile layouts and keyboard navigation. Review saves retain scroll; acceptance returns to the assignment normally.
- [ ] Repeat generation with JavaScript disabled; confirm the normal POST fallback and scroll restoration work.

## Availability

- [ ] Open the availability page.
- [ ] Add a weekly or one-time availability block.
- [ ] Confirm the availability block appears correctly.

## Study Plan

- [ ] Generate a study plan.
- [ ] Confirm study sessions fall inside the saved availability.
- [ ] Confirm sessions are scheduled before the assignment deadline.
- [ ] Mark one study session complete.
- [ ] Regenerate the plan.
- [ ] Confirm completed work is preserved after regeneration.

## User Protection

- [ ] Log in as a different test student.
- [ ] Confirm the other student cannot access the first student's assignment.
- [ ] Confirm the other student cannot see the first student's active study plan.

## Expected Result

The main CanvasGPT workflow should work completely offline with test data, without real Canvas credentials or external API calls.

## Insufficient Availability Check

- [ ] Create a checklist task that needs more study time than the saved availability allows.
- [ ] Generate the study plan.
- [ ] Confirm the task appears as unscheduled instead of being placed outside the available time.

### Expected Result

The planner should not schedule sessions outside the student's availability or after the assignment deadline. Tasks that do not have enough available time should be reported as unscheduled.