''' Blurs all weights in the selected vertex group.

This is still one of my first blender addons, so please keep in mind I may be
implementing various operations badly or just plain wrong.'''

'''
*******************************************************************************
	License and Copyright
	Copyright 2012 Jordan Hueckstaedt
	This program is free software: you can redistribute it and/or modify
	it under the terms of the GNU General Public License as published by
	the Free Software Foundation, either version 3 of the License, or
	(at your option) any later version.

	This program is distributed in the hope that it will be useful,
	but WITHOUT ANY WARRANTY; without even the implied warranty of
	MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
	GNU General Public License for more details.

	You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
'''

bl_info = {
	'name': 'Blur Weights',
	'author': 'Jordan Hueckstaedt',
	'version': (1, 0),
	'blender': (2, 63, 0),
	'location': 'View > Weight Tools > Blur',
	'warning': '', # used for warning icon and text in addons panel
	'description': 'Blurs the weights in the selected vertex group.',
	"wiki_url": "",
	"tracker_url": "",
	"support": 'TESTING',
	'category': 'Paint'
}

import bpy
import bmesh
import math
# from mathutils import *

class BlurSettingsCollection(bpy.types.PropertyGroup):
	iterations = bpy.props.IntProperty(
		name = "Iter", 
		description = "Iterate this many times",
		default = 1,
		min = 1,
		soft_max = 20)
	
	factor = bpy.props.FloatProperty(
		name = "Factor", 
		description = "Laplace Factor",
		default = 0.5,
		soft_min = 0.0,
		soft_max = 1.0)
	
	operation = bpy.props.EnumProperty(
		name="Blur Operation",
		items =	(('GAUSSIAN', "Gaussian", "Gaussian Blur"),
				('AVERAGE', "Average", "Simple Average Blur"),
				),
		)
	
	blur_type = bpy.props.EnumProperty(
		name="Blur Type",
		items =	(('0', "Normal", "Normal Blur"),
				('1', "Shrink", "Blur will only decrease values"),
				('2', "Grow", "Blur will only increase values"),
				),
		)


class BlurWeights( object ):
	def __init__(self, active_index = None):
		
		obj = bpy.context.active_object
		if active_index is None:
			active_index = obj.vertex_groups.active_index
		
		# Get a BMesh representation to access connectivity information
		bm_obj = bmesh.new()
		bm_obj.from_mesh(obj.data)
	
		# Find masking - this would be a lot more efficient if face masking
		# actually is the same as vertex masking.  Then the test could go in 
		# the "Get weight Info" loop easily.  But I'm not sure, so I'm doing it
		# this way to be safe.
		face_mask = obj.data.use_paint_mask
		vertex_mask = obj.data.use_paint_mask_vertex
		if face_mask or vertex_mask:
			if face_mask:
				masked_verts = set([v.index for f in bm_obj.faces if f.select for v in f.verts])
			else:
				masked_verts = set([v.index for v in bm_obj.verts if v.select])
		else:
			masked_verts = None
		
		weights = [1.0 for x in range(len(obj.data.vertices))]
		vert_indexes = []
		vert_group_indexes = []
		connected_verts = []
		gaussian_weights = []
		
		# Get weight info.  It's weird, I know
		for vert in obj.data.vertices:
			# Skip if vert is not in mask.
			if masked_verts is None or vert.index in masked_verts:
				for x, group_info in enumerate(vert.groups):
					if group_info.group == active_index:
						# Get group info
						weights[vert.index] = group_info.weight
						vert_indexes.append(vert.index)
						vert_group_indexes.append(x)
						break
		
		# Sets are MUCH faster to test in than lists.  This made __init__ run 3x faster for me.
		vert_indexes_test = set(vert_indexes)
		
		# Only use connected verts in which are in the group.  God this part was a bitch to get working.
		# Also, pre-calculate the guassian weights if needed
		for x in reversed(range(len(vert_indexes))):
			vert = bm_obj.verts[vert_indexes[x]]
			
			connected_vert = [v.index for edge in vert.link_edges for v in edge.verts if v.index != vert.index] and v.index in vert_indexes_test]			
			
			inclusive_verts = connected_vert + [vert.index]
			link_edges = [edge for edge in vert.link_edges if edge.verts[0].index in inclusive_verts and edge.verts[1].index in inclusive_verts]
			if not link_edges:
				# Orphaned vert
				vert_indexes.pop(x)
				vert_group_indexes.pop(x)
			else:
				connected_verts.append(connected_vert)

				# Pre-Calculate gaussian weights.
				avg_edge = sum([edge.calc_length() for edge in link_edges]) / len(link_edges)
				
				gaussian_weight = {'total_weight' : 0.0}
				for i in connected_vert:
					distance = (vert.co - bm_obj.verts[i].co).length_squared
					gaussian_weight[str(i)] = (1.0 /(avg_edge * math.sqrt(2.0 * math.pi))) * math.exp(-(distance)/(2.0 * avg_edge ** 2))
					gaussian_weight['total_weight'] += gaussian_weight[str(i)]
					
				gaussian_weights.append( gaussian_weight )
		
		# The last for loop was iterating in reverse to allow removing indexes while iterating.
		# So these lists are reversed
		gaussian_weights.reverse()
		connected_verts.reverse()
		
		self.weights = weights
		self.vert_indexes = vert_indexes
		self.vert_group_indexes = vert_group_indexes
		self.connected_verts = connected_verts
		self.gaussian_weights = gaussian_weights
		self.active_index = active_index
		bm_obj.free()
	
		
	def execute(self, iterations = 1, factor = 0.5, do_gaussian = True, blur_type = 0):
		''' Calculate the blurred weights.
		blur_type options:
		0 - Normal
		1 - Shrink
		2 - Grow
		'''
		
		# Whatever you do, never save obj to a class member variable.  Blender will freeze.
		obj = bpy.context.active_object
		
		# Make a copy of weights.  Otherwise edits will be compounded onto the initial weight set.
		weights = self.weights[:]
		
		for i in range(iterations):
			new_weights = weights
			for x, i in enumerate(self.vert_indexes):
				# Skip guassian if the denominator in the weight function is 0 
				# Which would most likely mean all the connected verts are in the same position
				if do_gaussian and self.gaussian_weights[x]['total_weight'] > 0.0:
					average_weight = 0
					for v in self.connected_verts[x]:
						average_weight += self.gaussian_weights[x][str(v)] / self.gaussian_weights[x]['total_weight'] * weights[v]
				else:
					average_weight = sum([weights[v] for v in self.connected_verts[x]]) / len(self.connected_verts[x])
				
				# Assign new weights with using laplace factor (or can I just call this a lerp? hmmm...)
				new_weights[i] = factor * average_weight + (1.0 - factor) * weights[i]
				
				# Grow or shrink weights.
				if blur_type == 1:
					new_weights[i] = min(new_weights[i], self.weights[i])
				elif blur_type == 2:
					new_weights[i] = max(new_weights[i], self.weights[i])
				
			weights = new_weights[:]

		# Update object weights
		for x, i in enumerate(self.vert_indexes):
			obj.data.vertices[i].groups[self.vert_group_indexes[x]].weight = weights[i]
		obj.data.update()

class WeightPaintBlurAll(bpy.types.Operator):
	bl_idname = "object.weightpaint_blur_all"
	bl_label = "Blur"
	bl_options = {'REGISTER', 'UNDO'}
	
	settings = bpy.props.PointerProperty(type = BlurSettingsCollection)
	
	active_index = None
	blur = None

	def draw(self, context):
		self.layout.prop(self.settings, "iterations", text = "Iter")
		# self.layout.prop(self, "factor")
		box = self.layout.box()
		row = box.row()
		row.prop(self.settings, "operation", expand = True)
		box = self.layout.box()
		row = box.row()
		row.prop(self.settings, "blur_type", expand = True)
		
	@classmethod
	def poll(cls, context):
		obj = context.active_object
		return (obj and obj.mode == 'WEIGHT_PAINT' and obj.type == 'MESH' and len(obj.vertex_groups) > 0)
	
	def execute(self, context):
		# Lots of addons seem to disable undo during execution.  For whatever reason, 
		# I had difficulty with the undo queue reliably being turned back on, so I'm leaving this out.
		# global_undo_state = context.user_preferences.edit.use_global_undo
		# context.user_preferences.edit.use_global_undo = False
		
		do_gaussian = self.settings.operation == 'GAUSSIAN'

		# Initialize the blur operator if it hasn't been.
		if self.blur is None:
			self.blur = BlurWeights( self.active_index )
		
		self.blur.execute( iterations = self.settings.iterations, 
			factor = self.settings.factor, do_gaussian = do_gaussian,
			blur_type = int(self.settings.blur_type))
		
		# This is a hack.  For some reason the active vertex group changes during execution,
		# Only when used from the Blur PANEL (not the regular blur buttons in the weight paint section)
		# And this seems to happen even when I touch NOTHING related to it (I tried commenting out the
		# blur operation and the active_index query in invoke).  I have...no clue.
		if self.active_index is not None:
			context.active_object.vertex_groups.active_index = self.active_index
		
		# context.user_preferences.edit.use_global_undo = global_undo_state
		return{'FINISHED'} 
	
	def invoke(self, context, event):
		for key, value in context.scene.weightpaint_blur_all_settings.items():
			self.settings[key] = value
		self.active_index = context.active_object.vertex_groups.active_index
		return self.execute(context)

def panel_func(self, context):	
	row = self.layout.row(align = True).split(0.35)
	row.alignment = 'EXPAND'
	row.operator("object.weightpaint_blur_all", text="Blur")
	scn = context.scene
	row.prop(scn.weightpaint_blur_all_settings, "iterations")


def register():
	bpy.utils.register_class(BlurSettingsCollection)
	bpy.utils.register_class(WeightPaintBlurAll)
	bpy.types.Scene.weightpaint_blur_all_settings = bpy.props.PointerProperty(type = BlurSettingsCollection)
	bpy.types.VIEW3D_PT_tools_weightpaint.append(panel_func)
	
def unregister():
	bpy.utils.unregister_class(WeightPaintBlurAll)
	bpy.types.VIEW3D_PT_tools_weightpaint.remove(panel_func)
	
	del bpy.types.Scene.weightpaint_blur_all_settings
	bpy.utils.unregister_class(BlurSettingsCollection)
if __name__ == "__main__":
	register()
