# Damn Simple ComfyUI Manager

Damn Simple ComfyUI Manager is a portable Windows application created through Vibe Coding to manage multiple local ComfyUI portable instances from a simple, contained interface.

It is designed for users who want to install, organize, launch, back up, freeze, and maintain different ComfyUI environments without manually jumping between folders, launchers, configuration files, and browser sessions.

The distributed application is intended to be a ready-to-use portable executable.

<a href="https://www.buymeacoffee.com/maddok" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-violet.png" alt="Buy Me a Coffee" style="height: 60px !important;width: 217px !important;" ></a>

If you think it's appropriate, if you liked my idea, if it was useful to you, buy me a gelato!

## Main Features

- Manage existing ComfyUI portable instances.
- Install new ComfyUI portable releases from GitHub.
- Choose the ComfyUI release version and portable hardware package.
- Keep each work folder independent with its own configuration.
- Start instances in Browser mode or Dedicated mode.
- Use a dedicated ComfyUI window with per-instance browser data.
- Create and restore targeted, customizable backups.
- Preserve backups even when an instance is deleted.
- Connect instances to a shared `common_models_folder`.
- Install optional components such as ComfyUI Manager, Triton, and Ultralytics.
- Freeze instances to prevent future updates.

## First Run

1. Put the portable executable inside its own folder.
2. Start the application from that folder.
3. On first launch, the app may create local files and subfolders next to the executable for its configuration, tools, and support data.
4. Select or create a Work Folder.
5. The app creates local configuration and support folders inside that Work Folder.
6. The main interface becomes available after the Work Folder is selected.

<img src="screenshots/first_start.png" alt="First Start of the software" width="800">

Each Work Folder has its own instances, settings, backups, browser cache, and shared model folder. This makes it possible to keep different ComfyUI environments separated from each other.

## Installed Instances

The Installed Instances section lets you manage ComfyUI instances already present in the selected Work Folder.

Available actions include:

- Open the instance folder.
- Remove the instance from the list.
- Create a backup.
- Start the instance.
- Update the instance.
- Freeze the instance.
- Install or reinstall ComfyUI Manager.
- Connect or disconnect `extra_model_paths.yaml` from the common model folder.
- Install Triton.
- Install Ultralytics.
- Delete the instance from disk while keeping its backups.

<img src="screenshots/instances.png" alt="Installed Instacnes section" width="800">

## Start Modes

`Browser` mode starts the selected instance normally through its `.bat` launcher. ComfyUI behaves as it usually does and can open in the system browser according to the selected launcher behavior.

`Dedicated` mode starts the selected instance and opens ComfyUI in a dedicated application window. This window is meant to be a clean ComfyUI-only environment, without address bars or extra browser controls.

The dedicated window stores browser data separately for each instance. This helps keep cookies, cache, and session data independent between different ComfyUI installations.

### Dedicated Window Commands

The dedicated window includes two small hidden commands:

- `Refresh`
- `Clean Cache`

To show them, move the mouse pointer to the top-left corner of the dedicated window. The commands appear for a few seconds and then hide automatically.

Use `Refresh` when the ComfyUI interface needs to be reloaded.

Use `Clean Cache` when custom node interfaces, JavaScript panels, or UI elements are not loading correctly. This clears the dedicated cache for that specific instance and reloads the page.

Both commands ask for confirmation before running.

## New Installation

The New Installation section downloads ComfyUI portable packages from GitHub.

1. Choose a ComfyUI version.
2. Choose a portable package.
3. Set an Instance Name or use the generated name.
4. Start the download and preparation process.

The app installs ComfyUI into a subfolder of the selected Work Folder. It does not install directly into the Work Folder root.

<img src="screenshots/installation.png" alt="New Installation section" width="800">

## Backup

The Backup section lists backups stored inside the selected Work Folder.

Backups are compressed files containing selected instance data only. The available backup items are selectable, so each backup can be customized depending on what you want to preserve:

- `workflows`
- `subgraphs`
- `custom_nodes`
- `extra_model_paths.yaml`

<img src="screenshots/backup.png" alt="Backup section" width="800">

A backup can include all of these items or only some of them.

Backups can be restored to the original instance or to another compatible instance. This is useful when moving settings, workflows, or custom nodes from one ComfyUI installation to another.

Restore operations ask for confirmation before overwriting files.

## Common Model Folder

Each Work Folder can contain a `common_models_folder` used to share model paths across multiple instances.

The app can update an instance `extra_model_paths.yaml` so ComfyUI reads models from the common folder. It can also disconnect the instance by renaming the active YAML back to `.example`.

This allows several ComfyUI instances to use a shared model library without duplicating large model files inside every installation.

## Notes

Damn Simple ComfyUI Manager is focused on local portable use. It is meant to keep ComfyUI instance management practical, compact, and easy to understand while still allowing separate work folders, separate instance settings, and dedicated per-instance browser sessions.

## License

Damn Simple ComfyUI Manager is released under the GNU General Public License v3.0.

Copyright (c) 2026 maddok.
