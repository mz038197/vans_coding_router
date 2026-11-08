# The key check names the Classes a Personal API Key may manage

Status: accepted. Amends ADR 0077.

An accepted Personal API Key returns `classes`, a list of `{"id": int, "name": str}`, in place of `owned_class_ids`. For an admin it lists every Class. For anyone else it lists the Classes that user owns. A Partner Service shows the name and keeps the id. The answer still carries no email, no personal name, and no key id. A Class name is not a person's name.

A Partner Service gives teacher standing only when `is_admin` is true or `classes` is not empty. A Personal API Key whose holder owns no Class and is not an admin is still accepted, and a Partner Service that has nothing for that holder to manage says so (road-test: 你沒有可管理的班級).

An empty `api_key`, or one that is only whitespace, is refused as `invalid`.

## Considered Options

- **Return only Class ids**: rejected. road-test cannot read this router's database, so a teacher would pick between bare numbers, and an admin, who received no ids at all, could not reach any Class.
- **Give road-test its own endpoint for Class names**: rejected. A second call and a second credential rule for data the key check already reads.
- **List only active Classes for an admin**: rejected. A teacher may review an ended Class's road-test results, and the admin supports that teacher.
