# Setting up the wheel FEA

This is the step-by-step for checking a rover wheel against the loads our terrain data gives us. It's written for Ansys Workbench (Static Structural), with notes for SolidWorks Simulation at the end.

## 1. Get the loads

Build the data first if you haven't (`python -m marswalk.build`), then run:

```bash
python -m marswalk.loads
```

This writes `fea/wheel_load_cases.csv`, which has the forces on one wheel for five cases, plus `fea/wheel_load_cases_inputs.json`, which records every assumption that went into them. With the current Mount Sharp data, the cases look like this:

| Case | What's happening | Fz (N) | Fx (N) | Fy (N) |
|---|---|---|---|---|
| LC1 | Parked on level ground | 558 | 0 | 0 |
| LC2 | Climbing a 26° slope straight up | 502 | 242 | 0 |
| LC3 | Parked across a 26° slope (downhill wheel) | 692 | 0 | 334 |
| LC4 | Driving onto a 12 cm ledge, with a 1.5 impact factor | 836 | 1449 | 0 |
| LC5 | A sharp rock pressing into the skin (over 400 mm²) | 753 | 0 | 0 |

x is along the direction of travel, y is sideways and z points into the ground.

The 26° slope and 12 cm ledge come from the ground under Curiosity's own stops on Mount Sharp. We use the 95th percentile rather than the single worst stop, so one bad cell in the elevation map can't set the design load. That slope is steeper than the 20° we let the crew rover drive in the route planner, which is on purpose: the wheel should survive a mistake.

If you want to try other numbers, pass them in directly:

```bash
python -m marswalk.loads --slope 20 --roughness 0.10
```

## 2. Geometry

Keep the model simple. It's there to show where the stress goes, not to copy Curiosity's exact wheel.

- A cylinder 500 mm across and 400 mm wide, modeled as a **surface body** (shell) for the skin.
- Skin thickness **0.75 mm**.
- **Grousers:** about 24 chevron or straight ribs on the outside, 7 mm tall and 3 mm thick. Straight ribs are fine for a first pass.
- A hub disk on one side (5 mm thick) with a 60 mm bore where the axle goes.

In SpaceClaim or DesignModeler, make the skin a surface and the grousers and hub solids, or keep everything as shells with their own thicknesses. Shells mesh much faster and work better for a 0.75 mm skin.

## 3. Material

Add **aluminum alloy 7075-T7351** in Engineering Data:

- Young's modulus: 71.7 GPa
- Poisson's ratio: 0.33
- Density: 2810 kg/m³
- Tensile yield strength: 435 MPa
- Ultimate tensile strength: 505 MPa

## 4. Mesh

- Skin: 5 mm shell elements in general, refined to **1 mm** under the contact patch for LC4 and LC5.
- Check the mesh with a convergence run: halve the element size at the patch and confirm the peak stress changes by less than about 5%.

## 5. Supports and loads

- **Fixed support** on the hub bore. That's the axle.
- For **LC1 to LC4**, apply the forces from the CSV as a **remote force** on a 40 by 100 mm patch at the bottom of the wheel, where it touches the ground. For LC4, put the patch on the front-bottom of the wheel, where it meets the ledge.
- For **LC5**, apply the force as a **pressure** on a 10 by 40 mm strip of skin *between two grousers*. That's the rock edge. Dividing the force by the strip area gives about 1.9 MPa.
- Set up each case as its own analysis, or as load steps in one analysis.

## 6. What to look at

- **Equivalent (von Mises) stress** on the skin and grousers. Compare the peak with the 435 MPa yield. The safety factor is yield divided by peak stress.
- **Total deformation**, to make sure the wheel doesn't fold in on itself.
- For LC5, look closely at the skin between the grousers. That's where Curiosity's wheels tore.

## 7. Sanity-check against the hand calculation

`python -m marswalk.loads` also prints a quick hand calculation for LC5. It treats the skin between two grousers as a small round plate pushed by a pointed rock:

- Punching shear: about 80 MPa, a safety factor of about 3
- Plate bending: about 2,800 MPa, far above yield

The bending number is rough (it assumes a 2 mm rock tip and a 50 mm span of skin), but it says clearly that a sharp rock can push a 0.75 mm skin past yield. That matches what actually happened to Curiosity. Your FEA peak for LC5 should be well above yield too. If it comes out tiny, check that the pressure is on the skin between grousers and not on a grouser.

Once LC5 fails, the obvious follow-up for the report is a design change: a thicker skin, more grousers (a shorter unsupported span), or a different alloy. Rerun the case and show how much each one helps.

## SolidWorks Simulation

The same steps work in a Static study. Use a sheet-metal or shell body for the skin, **Fixed Geometry** on the hub bore, **Force** on split faces for LC1 to LC4, and **Pressure** on a split face between two grousers for LC5. Apply a mesh control of 1 mm at the split faces.
