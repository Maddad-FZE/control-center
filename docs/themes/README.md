# Authoring a theme

Packs live in `themes/<slug>/` (shipped with the app, replaced on update) or `data/themes/<slug>/` (kept across updates).

```
themes/<slug>/
  theme.json
  DESIGN.md
  preview.png      optional
  templates/       optional Django overrides
  static/          skin.css and other assets, served as /static/themes/<slug>/…
```

`theme.json` schema is 1. Set `extends` to `wood` for a palette variant, or `null` for a full pack. See `docs/themes/CONTRACT.md` for hooks you must keep.

Scaffold one:

```
python manage.py new_theme my-theme --extends wood --name "My Theme"
python manage.py check_themes
python manage.py collectstatic --noinput
```

Restart the app after collectstatic. A new pack is not served until static files are collected.

The site uses one theme, stored on Site Settings. The first-run setup page writes it. A superuser changes it under Settings → Appearance. Preview stores the slug in that superuser's session only.
