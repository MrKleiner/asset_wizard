# Asset Wizard
Turn Blender into central asset distributor.
This makes use of Blender Asset Browser feature to make it easy to manage your
assets:

- Swiftly send assets to the software of your choice:
	- Marmoset
		- [X] Single Textures
		- [X] Materials
		- [ ] Models
	- Substance Painter
		- [ ] Single Textures
		- [ ] Materials
		- [ ] Models
	- Substance Sampler
		- [ ] Single Textures
		- [ ] Materials
	- Substance Designer
		- [ ] Single Textures
		- [ ] Materials
	- Blender (Extra features)
		- [ ] Single Textures
		- [ ] Materials
	- Mari
		- [ ] Single Textures
		- [ ] Materials
	- Maya
		- [ ] Single Textures
		- [ ] Materials
- Generate Blender asset catalogues with scripts and templates provided
with the addon.
- Generate Better material/model previews.
- Everything is linked, unles specifically told to do otherwise.
Don't waste your storage space with rubbish intermediate files.


# How To Install
All the integrations can be installed separately. Only install what is needed.

The main part of this addon is the Blender addon, which manages all the assets
and distributes them among other itergrations.

### Main, mandatory component: Blender addon
- Download the repository as .zip
- Extract the `wzrd_blender` folder into the Blender addons folder, which on
Windows is located at
`%appdata%/Blender Foundation/Blender/<BLENDER_VERSION>/scripts/addons`
- Restart Blender

### Marmoset
- Download the repository as .zip
- Extract the `wzrd_marmoset` folder to `%localAppData%/Marmoset Toolbag 4/plugins`
- Restart Marmoset